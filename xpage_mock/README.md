# xpage 接口契约 — LLM 中转层规范

> 本文档面向 **xpage 团队**，描述 feishu-relay-bot 调用 xpage 时的接口约定。
>
> 同目录下 `server.py` 是一份**可运行的 mock 实现**，包含本契约里所有的最小行为，可以直接当作参考实现。

## 1. 定位

xpage 在链路里的位置：

```
                外网                    内网
  ┌────────────┐    飞书 IM    ┌──────┐    HTTP    ┌────────┐    HTTP    ┌──────────┐
  │ relay      │ ←──────────→ │ bot  │ ←────────→ │ xpage  │ ←────────→ │ MP / 上游 │
  └────────────┘              └──────┘            └────────┘            └──────────┘
                              ↑
                              feishu-relay-bot 调 xpage
```

xpage 的职责：**把内网 LLM 网关（MP / 自建 / 多供应商）封装成一个统一入口，对下游 bot 只暴露三个 OpenAI/Anthropic 标准端点。**

xpage 不需要知道飞书、不需要知道 relay、不需要知道客户端来源。**对 xpage 来说，bot 就是普通客户端**。

## 2. 必须支持的端点

xpage 必须暴露**三个 HTTP 端点**：

| 端点 | 协议 | 说明 |
|------|------|------|
| `POST /v1/chat/completions` | OpenAI Chat Completions | 适合 GPT/Kimi/GLM 等 |
| `POST /v1/responses`        | OpenAI Responses API | GPT-5 系列首选 |
| `POST /v1/messages`         | Anthropic Messages | Claude 系列首选 |

请求/响应字段**完全沿用上游 LLM 厂商定义**，xpage 不改字段、不改 schema、不裁剪。

> 参考：
> - OpenAI: https://platform.openai.com/docs/api-reference/chat/create
> - OpenAI Responses: https://platform.openai.com/docs/api-reference/responses
> - Anthropic: https://docs.anthropic.com/en/api/messages

## 3. 鉴权

xpage 需要识别**两种鉴权 header**（任一即可）：

```
Authorization: Bearer <xpage_api_key>      ← OpenAI 风格
x-api-key: <xpage_api_key>                 ← Anthropic 风格
```

xpage 自己维护一份 key 清单（数据库 / 配置）。**bot 不会暴露最终客户端的 key**——bot 用一个固定的 xpage key 调，xpage 不需要知道下游客户端是谁。

> 这里有个未来扩展点：如果 xpage 想做"按客户端追溯"，可以让 bot 加一个 `X-Forwarded-Client: <relay_api_key_name>` header。这是可选能力，本契约暂不要求。

## 4. 鉴权后的行为

xpage 拿到合法请求后，**应该把请求转发到下游 LLM 网关并把响应原样返回**。具体：

### 4.1 请求转换（最小化）

```
client → xpage:          上游格式 + Authorization: Bearer <xpage_key>
xpage → 下游(MP/etc):    上游格式 + Authorization: Bearer <xpage 自己的 MP key>
```

xpage 替换 Authorization，其它请求体字段**不动**。

### 4.2 响应转换

下游响应原样回给 client，包括：
- HTTP status code
- response body（JSON / SSE 流）
- 上游的错误格式

**例外**：xpage 应该加一个响应头 `X-Xpage-Request-Id: <uuid>` 便于日志追踪。

## 5. 流式（SSE）支持

`stream: true` 的请求 xpage **必须支持**，下游什么样 xpage 就什么样转发。

实现要点：
- `Content-Type: text/event-stream`
- 不要 buffer，chunk 来了立刻往前推
- `Connection` / `Cache-Control` 头沿用下游
- nginx 等中间层注意关 buffering（`proxy_buffering off`）

## 6. 超时

| 客户端 → xpage | 至少 300s | Claude opus 偶发 100s+ |
| xpage → 下游 | 至少 300s | 同上 |

xpage 自己 timeout 短了会导致 client 拿到 504 而上游还在跑。

## 7. 错误返回

下游错误**原样**透传，包括 status code 和 body：

```json
// OpenAI 格式（chat / responses）
{"error": {"message": "...", "type": "...", "code": "..."}}

// Anthropic 格式（messages）
{"type": "error", "error": {"type": "...", "message": "..."}}
```

xpage 自身的错误（鉴权失败、上游不可达）也用对应路径的格式：
- `/v1/chat/completions` 和 `/v1/responses` 路径 → OpenAI 格式
- `/v1/messages` 路径 → Anthropic 格式

## 8. 健康检查

```
GET /health
→ 200 OK
  {"status": "ok", "upstream_reachable": true}
```

bot 不会主动调，只是运维方便。

## 9. 其他建议（可选）

- **请求日志**：每条请求记 method/path/key（脱敏）/status/duration/upstream-trace-id
- **限流**：可选。bot 端已经有限流，xpage 加一层能防客户端误用
- **Metrics**：Prometheus `/metrics` 端点（QPS、延迟分布、按 key 维度计数）

## 10. 验证清单

xpage 实现完成后，feishu-relay-bot 这边会跑这些测试：

```bash
# 1. 鉴权
curl -X POST $XPAGE/v1/chat/completions \
  -H "Authorization: Bearer wrong-key" -H "Content-Type: application/json" \
  -d '{"model":"...","messages":[...]}'
# 期望：401

# 2. 三种格式
curl -X POST $XPAGE/v1/chat/completions \
  -H "Authorization: Bearer $XPAGE_KEY" -H "Content-Type: application/json" \
  -d '{"model":"gpt-5.5","messages":[{"role":"user","content":"hi"}],"max_tokens":50}'
# 期望：OpenAI Chat 标准响应

curl -X POST $XPAGE/v1/responses \
  -H "Authorization: Bearer $XPAGE_KEY" -H "Content-Type: application/json" \
  -d '{"model":"gpt-5.5","input":"hi","max_output_tokens":50}'
# 期望：OpenAI Responses 标准响应

curl -X POST $XPAGE/v1/messages \
  -H "x-api-key: $XPAGE_KEY" -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-opus-4-7","max_tokens":50,"messages":[{"role":"user","content":"hi"}]}'
# 期望：Anthropic Messages 标准响应

# 3. 流式
curl -N -X POST $XPAGE/v1/chat/completions \
  -H "Authorization: Bearer $XPAGE_KEY" -H "Content-Type: application/json" \
  -d '{"model":"...","messages":[...],"stream":true}'
# 期望：SSE 流，逐 chunk 输出

# 4. 健康
curl $XPAGE/health
```

## 11. mock 实现位置

`xpage_mock/server.py` 是参考实现。本地启动：

```bash
pip install fastapi uvicorn httpx
UPSTREAM_MP_BASE=https://your-mp-base.com \
UPSTREAM_MP_KEY=mp-xxx \
XPAGE_LISTEN_KEYS=test-key-1,test-key-2 \
uvicorn xpage_mock.server:app --port 8800
```

xpage 团队对照这个 mock 的行为来实现，feishu-relay-bot 切换上游时只改 base URL 即可。
