"""
Bot ↔ Mock Memo 端到端测试（绕过飞书 WS，直接测上游 client）。

前置：
  在 xpage-admin-backend/scripts 目录先启动 mock_memo.py：
  POOL_KEYS=ak-xxx,ak-yyy python3 scripts/mock_memo.py

运行：
  cd /tmp/feishu-relay-bot
  python3 tests/test_e2e_mock_memo.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from feishu_relay_bot.config import UpstreamConfig
from feishu_relay_bot.models import DEFAULT_MODELS, ModelRegistry
from feishu_relay_bot.upstream import UpstreamClient


def _client(api_key="memopalace-default-token"):
    cfg = UpstreamConfig(
        base_url="http://127.0.0.1:8079",
        api_key=api_key,
        timeout_s=60,
        default_max_tokens=128,
    )
    return UpstreamClient(cfg, ModelRegistry(DEFAULT_MODELS))


def _ok(label, status, resp):
    icon = "✅" if status == 200 else "❌"
    content = resp.get("content", "")
    usage = resp.get("usage")
    print(f"  {icon} {label:20s} status={status} content={content[:60]!r} usage={usage}")
    if status != 200:
        raise AssertionError(f"{label} failed: {resp}")


def test_chat_glm():
    c = _client()
    status, resp = c.call_openai_chat_mode("glm-5.1", {
        "model": "glm-5.1",
        "messages": [{"role": "user", "content": "say ok"}],
        "max_tokens": 20,
    })
    _ok("GLM chat", status, resp)


def test_messages_claude():
    c = _client()
    status, resp = c.call_openai_chat_mode("claude-sonnet-4-6", {
        "model": "claude-sonnet-4-6",
        "messages": [{"role": "user", "content": "say ok"}],
        "max_tokens": 20,
    })
    _ok("Claude messages", status, resp)


def test_responses_gpt55():
    c = _client()
    status, resp = c.call_openai_chat_mode("gpt-5-5", {
        "model": "gpt-5-5",
        "messages": [{"role": "user", "content": "say ok"}],
        "max_tokens": 20,
    })
    _ok("GPT-5.5 responses", status, resp)


def test_auth_wrong_key():
    c = _client("wrong-key")
    status, resp = c.call_openai_chat_mode("glm-5.1", {
        "model": "glm-5.1",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 10,
    })
    icon = "✅" if status == 401 else "❌"
    print(f"  {icon} Auth wrong           status={status}")
    if status != 401:
        raise AssertionError(f"expected 401, got {status}: {resp}")


def test_temperature_passthrough():
    c = _client()
    status, resp = c.call_openai_chat_mode("glm-5.1", {
        "model": "glm-5.1",
        "messages": [{"role": "user", "content": "say ok"}],
        "max_tokens": 20,
        "temperature": 0.1,
    })
    _ok("Temperature", status, resp)


def test_top_p_passthrough():
    c = _client()
    status, resp = c.call_openai_chat_mode("glm-5.1", {
        "model": "glm-5.1",
        "messages": [{"role": "user", "content": "say ok"}],
        "max_tokens": 20,
        "top_p": 0.5,
    })
    _ok("Top-p", status, resp)


def test_native_claude():
    c = _client()
    status, resp = c.call_messages_native({
        "model": "claude-sonnet-4-6",
        "messages": [{"role": "user", "content": "say ok"}],
        "max_tokens": 20,
    })
    _ok("Native Claude", status, resp)


if __name__ == "__main__":
    print("=" * 50)
    print("Bot ↔ Mock Memo E2E Test")
    print("=" * 50)
    failed = 0
    for fn in (test_chat_glm, test_messages_claude, test_responses_gpt55,
               test_auth_wrong_key, test_temperature_passthrough,
               test_top_p_passthrough, test_native_claude):
        try:
            fn()
        except AssertionError as e:
            print(f"  ❌ {fn.__name__} FAILED: {e}")
            failed += 1
    print("=" * 50)
    print(f"Result: {7 - failed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
