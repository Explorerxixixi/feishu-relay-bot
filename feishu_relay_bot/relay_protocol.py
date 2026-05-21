"""
Relay 协议解析。

Relay → Bot 协议 v1（飞书 IM 文本消息）：

  默认模式（无 mode 字段）— OpenAI Chat 风格：
    {"_relay_v":1, "req_id":..., "model":..., "messages":[...],
     "temperature":0.7, "max_tokens":1000}

  Anthropic 原生模式（mode=messages_native）：
    {"_relay_v":1, "req_id":..., "mode":"messages_native",
     "model":"claude-opus-4-7", "messages":[...],
     "system":..., "max_tokens":..., "tools":[...], ...}

Bot → Relay 协议：

  成功（默认模式）:
    {"_relay_v":1, "req_id":..., "ok":true,
     "content":..., "usage":..., "finish_reason":...}

  成功（messages_native）:
    {"_relay_v":1, "req_id":..., "ok":true,
     "mode":"messages_native",
     "raw_anthropic": {...原 Anthropic 响应...}}

  失败:
    {"_relay_v":1, "req_id":..., "ok":false,
     "status":429, "error":..., "message":...}
"""
from __future__ import annotations

from typing import Optional


PROTOCOL_VERSION = 1


def parse_request(text: str) -> Optional[dict]:
    """
    把飞书 IM 消息文本（已经是 inner text，不含 wrapper）尝试解析为 relay 请求。
    返回 dict 或 None（非 relay 协议）。
    """
    import json
    try:
        d = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(d, dict):
        return None
    if d.get("_relay_v") != PROTOCOL_VERSION:
        return None
    if not d.get("req_id"):
        return None
    return d


def make_success_response(req_id: str, content: str, usage: dict, finish_reason: str) -> dict:
    """OpenAI Chat 模式成功响应。"""
    return {
        "_relay_v": PROTOCOL_VERSION,
        "req_id": req_id,
        "ok": True,
        "content": content,
        "usage": usage,
        "finish_reason": finish_reason,
    }


def make_native_success_response(req_id: str, raw_anthropic: dict) -> dict:
    """messages_native 模式成功响应。"""
    return {
        "_relay_v": PROTOCOL_VERSION,
        "req_id": req_id,
        "ok": True,
        "mode": "messages_native",
        "raw_anthropic": raw_anthropic,
    }


def make_error_response(
    req_id: str,
    status: int,
    error: str,
    message: str,
) -> dict:
    """通用失败响应。"""
    return {
        "_relay_v": PROTOCOL_VERSION,
        "req_id": req_id,
        "ok": False,
        "status": status,
        "error": error,
        "message": message,
    }
