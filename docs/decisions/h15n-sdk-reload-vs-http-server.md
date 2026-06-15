# H15n: SDK+Reload vs HTTP Server — OpenClaw+Feishu 多人持久化策略

**日期**: 2026-06-15
**状态**: 决策 → SDK+Reload 为主，HTTP Server 为 Web UI 保留

## 一、两种模式现状

SDK (`histrategy-sdk`) 已同时支持两种模式，均为 first-class API：

| 模式 | SDK 类 | 持久化 | 适用场景 |
|------|--------|--------|----------|
| **HTTP Server** | `ServerClient` | PostgreSQL (服务端) | Web UI, 实时多人 |
| **File Reload** | `Room` | `~/.histrategy/rooms/<name>/world_state.json` | Agent, CLI, IM Bot |
| **In-Process** | `DirectEngine` | `to_dict()` / `from_dict()` | 单次会话, 测试 |

## 二、OpenClaw + Feishu 场景分析

### 消息流特性

```
用户A (曹操) ──msg──→ Feishu ──webhook──→ OpenClaw ──invoke──→ histrategy-agent
                                                            │
                                                    TurnProcessor.execute()
                                                    ├── 1. load session from disk
                                                    ├── 2. parse intent (LLM)
                                                    ├── 3. execute command
                                                    ├── 4. generate narrative (LLM)
                                                    └── 5. save session to disk
                                                            │
用户B (刘备) ←──card── Feishu ←──────── OpenClaw ←── response
```

**关键特性**:
- 每次调用是一个**独立进程**（Agent 无状态，每次启动重新加载）
- 消息**天然串行**（IM 消息逐个到达）
- 状态必须**跨调用持久化**

### 两种方案对比

#### 方案 A: HTTP Server

```
Agent ──HTTP──→ histrategy server (24/7) ──DB──→ PostgreSQL
```

| 优点 | 缺点 |
|------|------|
| 多人协调内置（DecisionBus） | 需维护常驻服务器进程 |
| 强一致性（DB 事务） | 网络延迟：每回合 2 次 HTTP 往返 |
| WebSocket 实时推送 | 服务器宕机 = 游戏不可用 |
| | 部署复杂度（Docker + DB + 监控） |
| | 费用（服务器 + DB 托管） |

#### 方案 B: SDK+Reload（文件持久化）

```
Agent ──read──→ ~/.histrategy/sessions/feishu/{chat_id}/world_state.json
  │
  ├── 处理回合
  │
  └──write──→ ~/.histrategy/sessions/feishu/{chat_id}/world_state.json
```

| 优点 | 缺点 |
|------|------|
| 零运维（无服务器） | 并发写入需文件锁 |
| 零网络延迟（本地 I/O） | 多人"等待所有玩家"需额外实现 |
| 天然适合 Agent 无状态调用 | 无法实时推送（需 Feishu webhook 触发） |
| 已在 `GameSessionManager` 中实现 | |
| 已有 `Room` 类完美匹配此模式 | |

## 三、实际分析：IM Bot 不需要 HTTP Server

### 为什么 HTTP Server 的"多人协调"优势在此场景不成立

1. **IM 消息天然串行**：同一群聊中消息顺序到达，不存在"两个玩家同时提交决策"的并发问题
2. **Agent 调用是同步的**：OpenClaw 等待 histrategy-agent 返回后才响应 Feishu
3. **"等待所有玩家"在 IM 中是异步等待**：Player A 提交后，状态标记 `pending: [playerB, playerC]`，等 B 和 C 发消息时才推进回合

### 文件锁即可解决并发

```python
# SDK Room 类已实现
room = Room("feishu-group-42")
result = room.play("进攻襄阳")  # 自动 load → execute → save
```

如需多人安全：
```python
import fcntl
with open(lockfile, 'w') as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    room.play(decision)
```

## 四、推荐架构

```
                    ┌─────────────────────────────┐
                    │     histrategy-sdk           │
                    │                              │
  Feishu/OpenClaw   │  Room (file reload) ← 主力   │
  ───────────────→  │  ServerClient (HTTP) ← 备选  │
  Hermes Agent      │  DirectEngine       ← 测试   │
  ───────────────→  │                              │
                    └──────────┬──────────────────┘
                               │
                    ┌──────────▼──────────────────┐
                    │    histrategy-agent           │
                    │    GameSessionManager          │
                    │    TurnProcessor               │
                    │    StateBridge                 │
                    └──────────┬──────────────────┘
                               │
                    ┌──────────▼──────────────────┐
                    │    histrategy-engine          │
                    │    (deterministic engine)      │
                    └──────────────────────────────┘

持久化层: ~/.histrategy/
├── sessions/{platform}/{chat_id}/   ← Agent 场景
│   ├── world_state.json
│   └── session_meta.json
└── rooms/{name}/                     ← SDK Room 场景
    ├── world_state.json
    └── turns.jsonl
```

## 五、各场景路由

| 场景 | 推荐模式 | 持久化 |
|------|----------|--------|
| **Feishu 私聊** (单人) | `Room` (file) | `~/.histrategy/rooms/feishu-{user_id}/` |
| **Feishu 群聊** (多人) | `Room` (file) + 回合协调 | `~/.histrategy/rooms/feishu-group-{chat_id}/` |
| **OpenClaw IM** | `Room` (file) | `~/.histrategy/rooms/openclaw-{chat_id}/` |
| **Hermes Agent** | `GameSessionManager` (file) | `~/.histrategy/sessions/hermes/{chat_id}/` |
| **Web UI** (浏览器多人) | `ServerClient` (HTTP) | PostgreSQL |
| **CLI** (`histrategy --dev`) | `DirectEngine` | `~/.histrategy/world_state.json` |
| **E2E 测试** | `DirectEngine` | tmp path |

## 六、迁移路径（如果当前用了 HTTP Server）

当前 `histrategy-agent` 已经使用 `GameSessionManager`（文件模式），不需要迁移。

如果未来需要从文件迁移到 Server 模式（例如加 Web UI 观察 IM 游戏），SDK 的 `Room` 和 `ServerClient` 共享相同的 `TurnResult` 类型，切换只需改初始化代码：

```python
# 文件模式 → Server 模式：只改一行
# room = Room("my-game", faction="shu")
client = ServerClient()
room = MultiplayerRoom.join(client, room_id, faction, token)
```

## 七、决策

**SDK+Reload 模式为 OpenClaw+Feishu 的主力持久化方案。**

理由：
1. 已实现且工作正常（`Room` + `GameSessionManager`）
2. 零运维成本，适合 Agent 的无状态调用模式
3. IM 场景不存在真正的并发问题，文件锁足够
4. HTTP Server 保留给需要 Web UI + WebSocket 实时推送的 Web 客户端场景
5. 如果未来需要，从文件切换到 Server 的成本极低（SDK 抽象层统一接口）
