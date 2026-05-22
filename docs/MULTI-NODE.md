# 多节点部署架构

> 当多台机器各自部署了 feishu-relay-bot，需要理解通信隔离机制。

---

## 核心原则：一个飞书 App = 一条独立通道

```
┌──────────────────────────────────────────────────────────────┐
│  Gateway（外网入口）                                          │
│  relay_server.py                                             │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ BotPool: 管理多个 BotNode                                │ │
│  │  node-A (app_id=cli_aaa, chat_id=oc_xxx)                │ │
│  │  node-B (app_id=cli_bbb, chat_id=oc_yyy)                │ │
│  │  node-C (app_id=cli_ccc, chat_id=oc_zzz)                │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
         │              │              │
    飞书消息通道    飞书消息通道    飞书消息通道
   (P2P chat_id    (P2P chat_id    (P2P chat_id
    独立隔离)       独立隔离)       独立隔离)
         │              │              │
    ┌────┴────┐    ┌────┴────┐    ┌────┴────┐
    │ Node A  │    │ Node B  │    │ Node C  │
    │ 机器 1  │    │ 机器 2  │    │ 机器 3  │
    └─────────┘    └─────────┘    └─────────┘
```

**每个节点必须使用独立的飞书 App（不同的 `app_id` / `app_secret`）。**

### 为什么不能共用同一个 App？

飞书 IM P2P 聊天是基于「应用 ↔ 用户」的唯一关系：
- Gateway 用 `app_id=cli_aaa` 给用户 A 发消息 → P2P chat_id = `oc_xxx`
- 如果 Node-B 也用 `app_id=cli_aaa`，它的 ws 连接也会收到同一个 `oc_xxx` 频道的消息

**结果：多个 bot 共享消息通道，响应串扰，部分请求超时。**

### 正确做法

| 节点 | 飞书 App | 配置中的 app_id |
|------|----------|-----------------|
| Node A | relay-bot-a | `cli_aaaa...` |
| Node B | relay-bot-b | `cli_bbbb...` |
| Node C | relay-bot-c | `cli_cccc...` |

每个节点的 `config.yaml`：

```yaml
# Node A 的配置
bots:
  - name: node-a
    app_id: cli_aaaa...       # 独立的飞书 App
    app_secret: ${APP_SECRET}

center:
  enabled: true
  url: https://your-gateway.com/llm/api
  node_id: node-a             # 节点唯一标识
```

### 飞书开放平台批量创建 App

如果需要部署多个节点：

1. 登录 https://open.feishu.cn/app
2. 为每个节点创建一个新应用（名字如 `relay-bot-node-a`、`relay-bot-node-b`）
3. 每个应用都需要：
   - 权限：`im:message`、`im:message:send_as_bot`
   - 事件订阅：`im.message.receive_v1`
   - 长连接模式：开启
4. 每个应用发布并审批通过
5. Gateway 配置中注册对应 bot 的 open_id

### Gateway 侧配置

Gateway 需要知道每个节点对应的飞书 App，以便建立独立的通信通道：

```python
# bot_pool.py 中每个 BotNode 有独立的：
# - app_id / app_secret（用于发消息）
# - chat_id（P2P 唯一通道）
# - open_id（用于创建 P2P 聊天）
```

节点通过心跳自动注册到 Gateway。Gateway 根据 `open_id` 创建/获取 P2P `chat_id`。

---

## 负载均衡

Gateway 对已注册的节点做 Round-Robin 分发：

1. 请求到达 Gateway
2. Gateway 从健康节点列表中选一个（轮询）
3. 通过该节点对应的飞书通道发送请求
4. 等待该通道的响应（只看匹配 `req_id` 的消息）

### 节点健康判断

- 节点定期（30s）向 Gateway 心跳上报
- 超过 2 分钟无心跳 → 标记为 offline → 不参与分发
- 节点主动发送 offline 通知 → 立即下线

---

## 常见问题

**Q: 我只有一台机器，需要关心这些吗？**
A: 不需要。单节点直接部署即可，一个飞书 App 就够了。

**Q: 一台机器能跑多个 bot 对应多个 App 吗？**
A: 可以，config.yaml 的 `bots` 列表可以放多个。但没有必要 —— 多 bot 同机器的意义不大（除非是为了模型隔离）。

**Q: 两个节点用了同一个 App 会怎样？**
A: 两个 bot 都收到所有消息，各自处理并回复。Gateway 只取第一个回复，另一个浪费计算。更严重的是消息串扰可能导致超时或错误响应。
