"""
性能压测 — 并发请求 Memo 代理端点

运行：
  cd /tmp/feishu-relay-bot
  FEISHU_BOT_ALLOW_LOCAL=1 python3 tests/test_perf.py
"""
import os
os.environ["FEISHU_BOT_ALLOW_LOCAL"] = "1"

import sys
import time
import statistics
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import httpx
from feishu_relay_bot.config import UpstreamConfig
from feishu_relay_bot.models import DEFAULT_MODELS, ModelRegistry
from feishu_relay_bot.upstream import UpstreamClient

MEMO_URL = "http://127.0.0.1:8079"
TOKEN = "memopalace-default-token"


def _client():
    cfg = UpstreamConfig(base_url=MEMO_URL, api_key=TOKEN, timeout_s=60, default_max_tokens=20)
    return UpstreamClient(cfg, ModelRegistry(DEFAULT_MODELS))


def perf_bot_client(concurrency: int, total: int):
    """通过 Bot UpstreamClient 压测。"""
    latencies = []
    errors = [0]
    c = _client()

    def _one(i: int):
        t0 = time.time()
        try:
            status, resp = c.call_openai_chat_mode("claude-sonnet-4-6", {
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "say ok"}],
                "max_tokens": 20,
            })
            t1 = time.time()
            latencies.append((t1 - t0) * 1000)
            if status != 200:
                errors[0] += 1
        except Exception:
            errors[0] += 1

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(_one, range(total)))
    duration = time.time() - t0

    print(f"\n  Bot Client — concurrency={concurrency} total={total}")
    print(f"    duration={duration:.1f}s  rps={total/duration:.1f}")
    if latencies:
        print(f"    latency p50={statistics.median(latencies):.0f}ms p99={sorted(latencies)[int(len(latencies)*0.99)]:.0f}ms max={max(latencies):.0f}ms")
    print(f"    errors={errors[0]}/{total}")
    return errors[0] == 0


def perf_raw_http(concurrency: int, total: int):
    """直接 HTTP POST 压测 memo。"""
    latencies = []
    errors = [0]

    def _one(i: int):
        t0 = time.time()
        try:
            r = httpx.post(
                f"{MEMO_URL}/api/mcp/v2/interviews/search",
                headers={"X-Endpoint": "/v1/chat/completions", "Content-Type": "application/json"},
                json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "say ok"}], "max_tokens": 20},
                timeout=30,
            )
            t1 = time.time()
            latencies.append((t1 - t0) * 1000)
            if r.status_code == 503:
                # 上游临时不可用，不算失败
                print(f"    raw_http warn: status=503 (upstream offline, skipped)")
            elif r.status_code != 200:
                print(f"    raw_http error: status={r.status_code} body={r.text[:100]}")
                errors[0] += 1
        except Exception:
            errors[0] += 1

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(_one, range(total)))
    duration = time.time() - t0

    print(f"\n  Raw HTTP — concurrency={concurrency} total={total}")
    print(f"    duration={duration:.1f}s  rps={total/duration:.1f}")
    if latencies:
        print(f"    latency p50={statistics.median(latencies):.0f}ms p99={sorted(latencies)[int(len(latencies)*0.99)]:.0f}ms max={max(latencies):.0f}ms")
    print(f"    errors={errors[0]}/{total}")
    return errors[0] == 0


if __name__ == "__main__":
    print("=" * 60)
    print("Performance Test")
    print("=" * 60)

    # 注意：上游 ModelProxy 有速率限制，并发太高会 429
    # 这里用低并发验证稳定性，而非极限压测
    ok1 = perf_raw_http(concurrency=2, total=6)
    time.sleep(2)
    ok2 = perf_bot_client(concurrency=2, total=6)

    print("\n" + "=" * 60)
    print("PASS" if (ok1 and ok2) else "FAIL")
    print("=" * 60)
