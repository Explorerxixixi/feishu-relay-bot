"""
单个飞书 Bot 实例：一个 ws 连接 + 一个上游 client。
收到 relay 协议消息 → 路由到 upstream → 把响应打包发回飞书。
"""
from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import lark_oapi as lark
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

from .config import BotConfig
from .relay_protocol import (
    parse_request,
    make_success_response,
    make_native_success_response,
    make_error_response,
)
from .upstream import UpstreamClient


class Bot:
    """一个飞书 bot：维护 ws 连接 + 处理消息 + 调上游。"""

    def __init__(
        self,
        cfg: BotConfig,
        upstream: UpstreamClient,
        worker_threads: int = 32,
    ):
        self.cfg = cfg
        self.upstream = upstream
        self.logger = logging.getLogger(f"bot.{cfg.name}")
        self._executor = ThreadPoolExecutor(
            max_workers=worker_threads,
            thread_name_prefix=f"bot-{cfg.name}",
        )

        # lark 客户端（用来发消息）
        self._lark_client = lark.Client.builder() \
            .app_id(cfg.app_id) \
            .app_secret(cfg.app_secret) \
            .log_level(lark.LogLevel.WARNING) \
            .build()

        # ws 事件 handler
        handler = lark.EventDispatcherHandler.builder("", "") \
            .register_p2_im_message_receive_v1(self._on_message) \
            .build()

        self._ws_client = lark.ws.Client(
            cfg.app_id,
            cfg.app_secret,
            event_handler=handler,
            log_level=lark.LogLevel.WARNING,
        )

        self._thread: Optional[threading.Thread] = None

    # ---- 启停 ---------------------------------------------------------------

    def start(self) -> None:
        """启动 ws，子线程阻塞跑。"""
        if self._thread and self._thread.is_alive():
            self.logger.warning("already running")
            return
        self.logger.info("starting bot %s app_id=%s", self.cfg.name, self.cfg.app_id)
        self._thread = threading.Thread(
            target=self._ws_client.start,
            name=f"ws-{self.cfg.name}",
            daemon=True,
        )
        self._thread.start()

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ---- 事件处理 -----------------------------------------------------------

    def _on_message(self, data: lark.im.v1.P2ImMessageReceiveV1) -> None:
        event = data.event
        msg = event.message

        if msg.message_type != "text":
            self.logger.debug("ignore non-text msg: type=%s", msg.message_type)
            return

        try:
            content = json.loads(msg.content)
        except Exception:
            return
        raw_text = content.get("text", "")
        chat_id = msg.chat_id

        req = parse_request(raw_text)
        if req is None:
            self.logger.debug("ignore non-relay msg: %.60s", raw_text)
            return

        req_id = req["req_id"]
        mode = req.get("mode", "openai_chat")
        model = req.get("model", "")
        msgs = req.get("messages", [])
        self.logger.info(
            "← req_id=%s mode=%s model=%s msgs=%d",
            req_id, mode, model, len(msgs),
        )

        # 异步处理避免阻塞 ws 线程（飞书 ACK 限 3s）
        self._executor.submit(self._handle_request, req, chat_id)

    def _handle_request(self, req: dict, chat_id: str) -> None:
        """实际处理一条 relay 请求：调上游 → 发回飞书。"""
        req_id = req["req_id"]
        mode = req.get("mode", "openai_chat")
        try:
            if mode == "messages_native":
                self._handle_native(req, chat_id)
            else:
                self._handle_chat(req, chat_id)
        except Exception as e:
            self.logger.exception("处理 req_id=%s 异常", req_id)
            self._reply_json(chat_id, make_error_response(
                req_id, 500, "bot_exception", f"{type(e).__name__}: {e}",
            ))

    def _handle_chat(self, req: dict, chat_id: str) -> None:
        """OpenAI Chat 模式：归一化输出。"""
        req_id = req["req_id"]
        model = req.get("model", "")
        messages = req.get("messages", [])

        if not self.upstream.models.is_supported(model):
            self._reply_json(chat_id, make_error_response(
                req_id, 400, "unsupported_model",
                f"unsupported model: {model}",
            ))
            return

        status, resp = self.upstream.call_openai_chat_mode(
            model, messages,
            max_tokens=req.get("max_tokens"),
            temperature=req.get("temperature"),
        )

        if status == 200:
            self._reply_json(chat_id, make_success_response(
                req_id,
                content=resp["content"],
                usage=resp["usage"],
                finish_reason=resp["finish_reason"],
            ))
        else:
            err_msg = (
                resp.get("error") if isinstance(resp.get("error"), str)
                else (resp.get("msg") or str(resp)[:300])
            )
            self._reply_json(chat_id, make_error_response(
                req_id,
                status if status >= 400 else 502,
                "upstream_error",
                err_msg,
            ))

    def _handle_native(self, req: dict, chat_id: str) -> None:
        """Anthropic 原生透传模式。"""
        req_id = req["req_id"]
        # 把 relay 协议字段拿掉，剩下就是 Anthropic body
        payload = {
            k: v for k, v in req.items()
            if k not in ("_relay_v", "req_id", "mode")
        }

        status, resp = self.upstream.call_messages_native(payload)

        if status == 200 and "content" in resp:
            self._reply_json(chat_id, make_native_success_response(req_id, resp))
        else:
            err_msg = (
                resp.get("error", {}).get("message")
                if isinstance(resp.get("error"), dict)
                else resp.get("msg") or str(resp)[:300]
            )
            self._reply_json(chat_id, make_error_response(
                req_id,
                status if status >= 400 else 502,
                "upstream_error",
                err_msg,
            ))

    # ---- 发飞书消息 ---------------------------------------------------------

    def _reply_json(self, chat_id: str, payload: dict) -> None:
        text = json.dumps(payload, ensure_ascii=False)
        try:
            req = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("text")
                    .content(json.dumps({"text": text}, ensure_ascii=False))
                    .build()
                ).build()
            resp = self._lark_client.im.v1.message.create(req)
            if not resp.success():
                self.logger.error("回复失败: code=%s msg=%s", resp.code, resp.msg)
            else:
                self.logger.info(
                    "→ req_id=%s ok=%s len=%d",
                    payload.get("req_id"), payload.get("ok"), len(text),
                )
        except Exception as e:
            self.logger.exception("发送飞书消息异常: %s", e)
