"""
管控指令处理：升级、重启、优雅下线。

安全要求：
  - 所有 ctrl 消息必须带 HMAC-SHA256 签名（字段 key="signature"）
  - 签名密钥从环境变量 FEISHU_BOT_CTRL_SECRET 读取
  - 未配置密钥或签名不匹配 → 拒绝执行并记录警告
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .bot import Bot

logger = logging.getLogger("feishu-relay-bot.ctrl")

_CTRL_SECRET = os.environ.get("FEISHU_BOT_CTRL_SECRET", "")


def _verify_signature(msg: dict) -> bool:
    """校验 ctrl 消息的 HMAC-SHA256 签名。"""
    if not _CTRL_SECRET:
        return False

    expected = msg.get("signature", "")
    if not expected:
        return False

    # payload = 除 signature 外所有字段按 key 排序后的 JSON
    payload = {k: v for k, v in msg.items() if k != "signature"}
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    computed = hmac.new(_CTRL_SECRET.encode(), payload_bytes, hashlib.sha256).hexdigest()

    # Length check first (cheap & would short-circuit compare_digest anyway),
    # so that an attacker cannot use a long/truncated "signature" to leak timing.
    if len(computed) != len(expected):
        return False

    return hmac.compare_digest(computed, expected)


def handle_ctrl(bot: "Bot", msg: dict):
    """处理来自 Gateway 的管控指令。"""
    action = msg.get("action", "")
    logger.info("收到管控指令: action=%s", action)

    if not _verify_signature(msg):
        return

    if action == "upgrade":
        target_version = msg.get("target_version", "latest")
        _do_upgrade(target_version)
    elif action == "restart":
        _do_restart()
    elif action == "drain":
        _do_drain(bot)
    else:
        logger.warning("未知管控指令: %s", action)


def _do_upgrade(target_version: str):
    """升级 bot 包并退出（systemd 会自动重启）。"""
    from .upgrade import upgrade_and_exit
    upgrade_and_exit(target_version)


def _do_restart():
    """直接退出，由 systemd 重启。"""
    import sys
    logger.info("执行重启: exit(0)")
    sys.exit(0)


def _do_drain(bot: "Bot"):
    """优雅下线：停止接新请求，等现有请求处理完，退出。"""
    import sys
    import time
    logger.info("执行优雅下线: drain")
    bot._executor.shutdown(wait=True, cancel_futures=True)
    time.sleep(5)
    sys.exit(0)
