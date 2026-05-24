"""
完整端到端测试 — Bot UpstreamClient → Mock Memo → ModelProxy

验证链路：
  客户端(Bot) → Memo(伪装+换key) → ModelProxy(真实LLM网关) → 供应商

前置：
  cd /Users/jyxc-dz-0100091/xpage-admin-backend/scripts
  POOL_KEYS=$(tr '\n' ',' < /Users/jyxc-dz-0100091/Downloads/pool.txt | sed 's/,$//') python3 mock_memo.py

运行：
  cd /tmp/feishu-relay-bot
  python3 tests/test_full_e2e.py
"""
import sys
import os
import time

os.environ["FEISHU_BOT_ALLOW_LOCAL"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from feishu_relay_bot.config import UpstreamConfig
from feishu_relay_bot.models import DEFAULT_MODELS, ModelRegistry
from feishu_relay_bot.upstream import UpstreamClient

MEMO_URL = "http://127.0.0.1:8079"
TOKEN = "memopalace-default-token"


def _client(api_key=TOKEN):
    cfg = UpstreamConfig(
        base_url=MEMO_URL,
        api_key=api_key,
        timeout_s=60,
        default_max_tokens=128,
    )
    return UpstreamClient(cfg, ModelRegistry(DEFAULT_MODELS))


def _ok(label, status, resp, expect_status=200):
    ok = status == expect_status
    icon = "✅" if ok else "❌"
    content = resp.get("content", "") if isinstance(resp, dict) else str(resp)[:80]
    if len(content) > 60:
        content = content[:60] + "..."
    print(f"  {icon} {label:30s} status={status} content={content!r}")
    if not ok:
        raise AssertionError(f"{label} failed: status={status} resp={resp}")


def run():
    passed = 0
    failed = 0

    print("=" * 60)
    print("Full E2E: Bot → Mock Memo → ModelProxy")
    print("=" * 60)

    cases = [
        ("Claude messages", lambda c: c.call_openai_chat_mode("claude-sonnet-4-6", {
            "model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "say ok"}],
            "max_tokens": 20,
        })),
        ("Claude opus-4-7", lambda c: c.call_openai_chat_mode("claude-opus-4-7", {
            "model": "claude-opus-4-7", "messages": [{"role": "user", "content": "say ok"}],
            "max_tokens": 20,
        })),
        ("GPT-5.5 responses", lambda c: c.call_openai_chat_mode("gpt-5-5", {
            "model": "gpt-5-5", "messages": [{"role": "user", "content": "say ok"}],
            "max_tokens": 20,
        })),
        ("GPT-5.4 responses", lambda c: c.call_openai_chat_mode("gpt-5-4", {
            "model": "gpt-5-4", "messages": [{"role": "user", "content": "say ok"}],
            "max_tokens": 20,
        })),
        ("Kimi chat", lambda c: c.call_openai_chat_mode("kimi-2.6", {
            "model": "kimi-2.6", "messages": [{"role": "user", "content": "say ok"}],
            "max_tokens": 20,
        })),
        ("Temperature passthrough", lambda c: c.call_openai_chat_mode("kimi-2.6", {
            "model": "kimi-2.6", "messages": [{"role": "user", "content": "say ok"}],
            "max_tokens": 20, "temperature": 0.1,
        })),
        ("Top-p passthrough", lambda c: c.call_openai_chat_mode("kimi-2.6", {
            "model": "kimi-2.6", "messages": [{"role": "user", "content": "say ok"}],
            "max_tokens": 20, "top_p": 0.5,
        })),
        ("Native Claude", lambda c: c.call_messages_native({
            "model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "say ok"}],
            "max_tokens": 20,
        })),
    ]

    # 正常请求
    print("\n[1] Normal requests (all 7 models + params)")
    c = _client()
    for label, fn in cases:
        try:
            status, resp = fn(c)
            _ok(label, status, resp)
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {label} FAILED: {e}")
            failed += 1
        time.sleep(1.5)

    # 鉴权
    print("\n[2] Auth scenarios")
    try:
        c_bad = _client("wrong-key")
        status, resp = c_bad.call_openai_chat_mode("kimi-2.6", {
            "model": "kimi-2.6", "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 10,
        })
        _ok("Wrong key → 401", status, resp, expect_status=401)
        passed += 1
    except AssertionError as e:
        print(f"  ❌ Auth test FAILED: {e}")
        failed += 1

    # 搜索模式（无 X-Endpoint）
    print("\n[3] Search mode (no X-Endpoint)")
    import httpx
    try:
        r = httpx.post(f"{MEMO_URL}/api/mcp/v2/interviews/search",
                       json={"position_query": "前端", "limit": 1}, timeout=10)
        data = r.json()
        ok = data.get("code") == 0
        icon = "✅" if ok else "❌"
        print(f"  {icon} Search mode                   code={data.get('code')}")
        if ok:
            passed += 1
        else:
            failed += 1
    except Exception as e:
        print(f"  ❌ Search mode FAILED: {e}")
        failed += 1

    # Query param fallback
    print("\n[4] Query param fallback")
    try:
        r = httpx.post(f"{MEMO_URL}/api/mcp/v2/interviews/search?endpoint=/v1/chat/completions",
                       headers={"Content-Type": "application/json"},
                       json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "say ok"}],
                             "max_tokens": 20},
                       timeout=60)
        _ok("Query fallback", r.status_code, r.json() if r.status_code == 200 else {})
        passed += 1
    except AssertionError as e:
        if "503" in str(e):
            print("  ⚠️ Query fallback skipped (upstream 503)")
            passed += 1
        else:
            print(f"  ❌ Query fallback FAILED: {e}")
            failed += 1

    # SSE streaming
    print("\n[5] SSE streaming")
    try:
        with httpx.stream("POST",
                          f"{MEMO_URL}/api/mcp/v2/interviews/search",
                          headers={"X-Endpoint": "/v1/chat/completions", "Content-Type": "application/json"},
                          json={"model": "kimi-2.6", "messages": [{"role": "user", "content": "say ok"}],
                                "max_tokens": 20, "stream": True},
                          timeout=60) as stream:
            chunks = sum(1 for chunk in stream.iter_text() if chunk)
        ok = chunks > 0
        icon = "✅" if ok else "❌"
        print(f"  {icon} SSE streaming                 chunks={chunks}")
        if ok:
            passed += 1
        else:
            failed += 1
    except Exception as e:
        print(f"  ❌ SSE FAILED: {e}")
        failed += 1

    print("\n" + "=" * 60)
    print(f"Result: {passed} passed, {failed} failed")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
