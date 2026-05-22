"""
Relay 协议解析 / 构建（v1 + v2 兼容）。

协议 v2 消息格式：
  所有消息带 _relay_v: 2 + type 字段。

  请求 (Gateway → Bot):
    {"_relay_v":2, "type":"req", "req_id":..., "model":..., "endpoint":"chat"|"messages"|"responses",
     "messages":[...], "temperature":0.7, "max_tokens":1000}

    messages_native 模式额外带 mode:"messages_native"，body 是完整 Anthropic 格式。

  响应 (Bot → Gateway):
    {"_relay_v":2, "type":"resp", "req_id":..., "node_id":..., "ok":true,
     "content":..., "usage":..., "finish_reason":...}

    messages_native 成功:
    {"_relay_v":2, "type":"resp", "req_id":..., "node_id":..., "ok":true,
     "mode":"messages_native", "raw_anthropic":{...}}

    失败:
    {"_relay_v":2, "type":"resp", "req_id":..., "node_id":..., "ok":false,
     "status":429, "error":..., "message":...}

  心跳 (Bot → Gateway):
    {"_relay_v":2, "type":"heartbeat", "node_id":..., "version":..., ...}

  管控 (Gateway → Bot):
    {"_relay_v":2, "type":"ctrl", "action":"upgrade"|"restart"|"drain", ...}

兼容 v1：parse_request 同时接受 _relay_v:1 的旧格式。
"""
from __future__ import annotations

from typing import Optional


PROTOCOL_VERSION = 2


def parse_request(data: dict) -> Optional[dict]:
    """
    解析 relay 请求。接受 v1 和 v2 格式。
    返回 dict 或 None（非 relay 协议）。

    注意：调用方负责 JSON 解析和 codec 解码，这里接收已解析的 dict。
    """
    if not isinstance(data, dict):
        return None
    version = data.get("_relay_v")
    if version not in (1, 2):
        return None
    if not data.get("req_id"):
        return None
    return data


def parse_message(data: dict) -> Optional[dict]:
    """
    解析任意 relay v2 消息（req/resp/heartbeat/ctrl）。
    返回 dict 或 None。
    """
    if not isinstance(data, dict):
        return None
    if data.get("_relay_v") != 2:
        return None
    if not data.get("type"):
        return None
    return data


def make_success_response(
    req_id: str,
    node_id: str,
    content: str,
    usage: dict,
    finish_reason: str,
) -> dict:
    """OpenAI Chat 模式成功响应 (v2)。"""
    return {
        "_relay_v": PROTOCOL_VERSION,
        "type": "resp",
        "req_id": req_id,
        "node_id": node_id,
        "ok": True,
        "content": content,
        "usage": usage,
        "finish_reason": finish_reason,
    }


def make_native_success_response(
    req_id: str,
    node_id: str,
    raw_anthropic: dict,
) -> dict:
    """messages_native 模式成功响应 (v2)。"""
    return {
        "_relay_v": PROTOCOL_VERSION,
        "type": "resp",
        "req_id": req_id,
        "node_id": node_id,
        "ok": True,
        "mode": "messages_native",
        "raw_anthropic": raw_anthropic,
    }


def make_error_response(
    req_id: str,
    node_id: str,
    status: int,
    error: str,
    message: str,
) -> dict:
    """通用失败响应 (v2)。"""
    return {
        "_relay_v": PROTOCOL_VERSION,
        "type": "resp",
        "req_id": req_id,
        "node_id": node_id,
        "ok": False,
        "status": status,
        "error": error,
        "message": message,
    }


def make_heartbeat(node_id: str, **extra) -> dict:
    """构建心跳消息 (v2)。"""
    return {
        "_relay_v": PROTOCOL_VERSION,
        "type": "heartbeat",
        "node_id": node_id,
        **extra,
    }
