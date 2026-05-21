"""
xpage Mock Server — LLM 中转层参考实现

提供给 xpage 团队作为接口契约的可执行参考。
本 mock 完全实现了"纯透传"的最小必要能力：
  - 鉴权（Bearer / x-api-key 双兼容）
  - POST /v1/chat/completions    OpenAI Chat 透传
  - POST /v1/responses           OpenAI Responses 透传
  - POST /v1/messages            Anthropic Messages 透传（含 stream）
  - GET  /health                 健康检查

启动:
  uvicorn xpage_mock.server:app --port 8800

环境变量:
  UPSTREAM_MP_BASE      下游 LLM 网关 base URL
  UPSTREAM_MP_KEY       下游 API key
  XPAGE_LISTEN_KEYS     允许的客户端 key（逗号分隔），默认 'test-key-1'
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse


UPSTREAM_BASE = os.getenv(
    "UPSTREAM_MP_BASE",
    "https://models-proxy.stepfun-inc.com",
).rstrip("/")
UPSTREAM_KEY = os.getenv("UPSTREAM_MP_KEY", "")
LISTEN_KEYS = set(
    k.strip()
    for k in os.getenv("XPAGE_LISTEN_KEYS", "test-key-1").split(",")
    if k.strip()
)
TIMEOUT_S = int(os.getenv("XPAGE_TIMEOUT_S", "300"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("xpage-mock")

app = FastAPI(
    title="xpage Mock",
    version="0.0.1",
    description=(
        "LLM 中转层参考实现 - 纯透传 OpenAI/Anthropic 原生协议到下游。"
    ),
)


# ============================================================================
# 鉴权
# ============================================================================


def _extract_key(request: Request) -> Optional[str]:
    """从 x-api-key 或 Authorization: Bearer 提取 key。"""
    k = request.headers.get("x-api-key", "")
    if k:
        return k
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def _check_key(request: Request) -> str:
    key = _extract_key(request)
    if not key or key not in LISTEN_KEYS:
        raise HTTPException(401, "Invalid xpage api key")
    return key


# ============================================================================
# 透传核心
# ============================================================================


async def _proxy(path: str, request: Request) -> JSONResponse | StreamingResponse:
    """通用透传到下游。"""
    _check_key(request)

    body_bytes = await request.body()
    req_id = uuid.uuid4().hex[:16]

    # 透传给下游：Authorization 用 xpage 的 upstream key
    headers_out = {
        "Authorization": f"Bearer {UPSTREAM_KEY}",
        "Content-Type": request.headers.get("Content-Type", "application/json"),
    }
    # Anthropic 需要这个 header
    av = request.headers.get("anthropic-version")
    if av:
        headers_out["anthropic-version"] = av

    url = f"{UPSTREAM_BASE}{path}"
    logger.info(
        "[%s] → %s %s (body=%d bytes)",
        req_id, request.method, url, len(body_bytes),
    )

    # 看是否是 stream 请求（body 里 stream:true）
    is_stream = b'"stream":true' in body_bytes or b'"stream": true' in body_bytes

    if is_stream:
        # 流式：保持 SSE 透传
        return StreamingResponse(
            _stream_proxy(url, headers_out, body_bytes, req_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Xpage-Request-Id": req_id,
            },
        )

    # 非流式：一把梭
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as cli:
        try:
            r = await cli.post(url, headers=headers_out, content=body_bytes)
        except httpx.TimeoutException:
            logger.warning("[%s] upstream timeout", req_id)
            raise HTTPException(504, "Upstream timeout")
        except Exception as e:
            logger.error("[%s] upstream error: %s", req_id, e)
            raise HTTPException(502, f"Upstream error: {e}")

    logger.info("[%s] ← %d (body=%d bytes)", req_id, r.status_code, len(r.content))

    # 试着按 JSON 返回，否则原样返回 bytes
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text[:500]}
    return JSONResponse(
        status_code=r.status_code,
        content=data,
        headers={"X-Xpage-Request-Id": req_id},
    )


async def _stream_proxy(url: str, headers: dict, body: bytes, req_id: str):
    """流式透传：把下游 SSE chunks 一段段往前转。"""
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as cli:
        async with cli.stream("POST", url, headers=headers, content=body) as r:
            async for chunk in r.aiter_bytes():
                if chunk:
                    yield chunk
    logger.info("[%s] ← stream done", req_id)


# ============================================================================
# Routes
# ============================================================================


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    return await _proxy("/v1/chat/completions", request)


@app.post("/v1/responses")
async def responses(request: Request):
    return await _proxy("/v1/responses", request)


@app.post("/v1/messages")
async def messages(request: Request):
    return await _proxy("/v1/messages", request)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "upstream": UPSTREAM_BASE,
        "listen_keys_count": len(LISTEN_KEYS),
    }


@app.get("/")
async def root():
    return {
        "service": "xpage-mock",
        "version": "0.0.1",
        "endpoints": {
            "openai_chat": "POST /v1/chat/completions",
            "openai_responses": "POST /v1/responses",
            "anthropic_messages": "POST /v1/messages",
            "health": "GET /health",
        },
        "auth": "Authorization: Bearer <key> | x-api-key: <key>",
    }
