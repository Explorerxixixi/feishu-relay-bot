"""
本地直连 HTTP Server：绕过飞书消息层，让 Gateway 直接 HTTP 调用 Bot。

接收编码后的 relay payload，内部走 Bot._handle_request 处理，返回 JSON 响应。
"""
from __future__ import annotations

import json
import logging
from typing import Optional

try:
    from fastapi import FastAPI, Request
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

logger = logging.getLogger("local-server")

_local_bot = None
_app: Optional[FastAPI] = None


def set_bot(bot):
    """把 Bot 实例注入进来（由 BotManager 启动时调用）。"""
    global _local_bot
    _local_bot = bot


def build_app() -> FastAPI:
    if not HAS_FASTAPI:
        raise RuntimeError("fastapi not installed, local server unavailable")
    app = FastAPI(title="Feishu Bot Local Relay")

    @app.post("/relay")
    async def relay(req: Request):
        if _local_bot is None:
            return {"ok": False, "status": 503, "message": "bot not ready"}

        body = await req.json()
        encoded = body.get("encoded", "")
        if not encoded:
            return {"ok": False, "status": 400, "message": "missing encoded"}

        # decode relay payload
        from .relay_codec import decode as codec_decode
        try:
            payload = codec_decode(encoded)
        except Exception as e:
            return {"ok": False, "status": 400, "message": f"decode error: {e}"}

        if not isinstance(payload, dict):
            return {"ok": False, "status": 400, "message": "invalid payload"}

        req_id = payload.get("req_id", "")

        # 临时替换 _reply_json 为收集器，避免真发飞书消息
        collected = []

        def collect_reply(chat_id, resp):
            collected.append(resp)

        original_reply = _local_bot._reply_json
        _local_bot._reply_json = collect_reply
        try:
            mode = payload.get("mode", "openai_chat")
            if mode == "messages_native":
                _local_bot._handle_native(payload, "local")
            else:
                _local_bot._handle_chat(payload, "local")
        except Exception as e:
            logger.exception("local relay error")
            return {"ok": False, "status": 500, "message": str(e), "req_id": req_id}
        finally:
            _local_bot._reply_json = original_reply

        if collected:
            return collected[0]
        return {"ok": False, "status": 500, "message": "no response", "req_id": req_id}

    @app.get("/health")
    async def health():
        return {"status": "ok", "bot_ready": _local_bot is not None}

    return app


def get_app():
    global _app
    if _app is None:
        _app = build_app()
    return _app
