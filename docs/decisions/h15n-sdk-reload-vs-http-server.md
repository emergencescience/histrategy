# H15n: SDK+Reload vs HTTP Server — OpenClaw+Feishu 多人持久化策略

**日期**: 2026-06-15
**状态**: ✅ 已决策 → SDK+Reload 为主，HTTP Server 为 Web UI 保留
**审阅**: Claude Sonnet 4.6 (2026-06-15)

---

> **[审阅意见]** 核心决策正确。补充了 3 点：(1) `SQLite` 优先于裸文件，(2) 文件锁并发控制有跨进程 Bug 风险需说明，(3) `room_manager.py` 的内存 dict 缓存是当前主要技术债务。

---

## 一、两种模式现状

SDK (`histrategy-sdk`) 已同时支持两种模式，均为 first-class API：

| 模式 | SDK 类 | 持久化 | 适用场景 |
|------|--------|--------|----------|
| **HTTP Server** | `ServerClient` | PostgreSQL (服务端) | Web UI, 实时多人 |
| **File Reload** | `Room` | `~/.histrategy/rooms/<name>/world_state.json` | Agent, CLI, IM Bot |
| **In-Process** | `DirectEngine` | `to_dict()` / `from_dict()` | 单次会话, 测试 |

> **[审阅补充]** `File Reload` 应升级为 **SQLite Reload**。原因：JSON 文件在并发写入时即使有 `fcntl.flock` 也无法保证原子性（crash 后文件可能半写）；SQLite WAL 模式提供事务保证，且读写性能相当。当前 `room_manager.py` 已有 SQLite 支持，迁移成本低。

---

## 二、OpenClaw + Feishu 场景分析

### 消息流特性

```
用户A (曹操) ──msg──→ Feishu ──webhook──→ OpenClaw ──invoke──→ histrategy-agent
                                                            │
                                                    TurnProcessor.execute()
                                                    ├── 1. load session (SQLite)
                                                    ├── 2. parse intent (LLM)
                                                    ├── 3. execute command
                                                    ├── 4. generate narrative (LLM)
                                                    └── 5. save session (SQLite)
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

#### 方案 B: SDK+SQLite Reload（**推荐**）

```
Agent ──read──→ ~/.histrategy/rooms/{room_id}.db
  │              (SQLite WAL, world_state 表)
  ├── 处理回合
  │
  └──write──→   ~/.histrategy/rooms/{room_id}.db
               (事务写入，原子性保证)
```

| 优点 | 缺点 / 注意事项 |
|------|----------------|
| 零运维（无服务器） | ⚠️ 多人"等待所有玩家"需额外实现 |
| 零网络延迟（本地 I/O） | ⚠️ 无法实时推送（需 Feishu webhook 触发） |
| 天然适合 Agent 无状态调用 | — |
| SQLite WAL 提供写入原子性 | — |
| 已在 `GameSessionManager` 中实现 | — |

---

## 三、实际分析：IM Bot 不需要 HTTP Server

### 为什么 HTTP Server 的"多人协调"优势在此场景不成立

1. **IM 消息天然串行**：同一群聊中消息顺序到达，不存在"两个玩家同时提交决策"的并发问题
2. **Agent 调用是同步的**：OpenClaw 等待 histrategy-agent 返回后才响应 Feishu
3. **"等待所有玩家"在 IM 中是异步等待**：Player A 提交后，状态标记 `pending: [playerB, playerC]`，等 B 和 C 发消息时才推进回合

### SQLite WAL 即可解决并发

```python
# GameSessionManager 已实现（session.py）
async with GameSessionManager(room_id) as session:
    result = await session.play(decision)  # 自动 load → execute → save (事务)
```

> **[审阅意见]** 原文档建议 `fcntl.flock` 文件锁，但这有缺陷：
> - Python 进程 crash 时文件锁自动释放，但 JSON 文件可能处于半写状态
> - `fcntl.flock` 是**咨询锁**（advisory lock），不能阻止不使用锁的进程直接写入
>
> **建议改用 SQLite 事务**：`BEGIN EXCLUSIVE` 在事务期间排他锁定数据库，crash 后自动回滚，比文件锁更健壮。当前 `session.py` 的 SQLite 实现已经提供这个保证，无需额外文件锁。

---

## 四、推荐架构（已修订）

```
                    ┌─────────────────────────────┐
                    │     histrategy-sdk           │
                    │                              │
  Feishu/OpenClaw   │  Room (SQLite) ← 主力        │
  ───────────────→  │  ServerClient (HTTP) ← 备选  │
  Hermes Agent      │  DirectEngine       ← 测试   │
  ───────────────→  │                              │
                    └──────────┬──────────────────┘
                               │
                    ┌──────────▼──────────────────┐
                    │    histrategy-agent          │
                    │    GameSessionManager         │
                    │    TurnProcessor              │
                    │    StateBridge                │
                    └──────────┬──────────────────┘
                               │
                    ┌──────────▼──────────────────┐
                    │    histrategy-engine         │
                    │    (deterministic engine)    │
                    └──────────────────────────────┘

持久化层: ~/.histrategy/
├── sessions/{platform}/{chat_id}/   ← Agent 场景
│   ├── game.db                      ← SQLite（WAL 模式）
│   └── session_meta.json
└── rooms/{name}/                    ← SDK Room 场景
    ├── game.db                      ← SQLite（WAL 模式）
    └── turns.jsonl                  ← append-only 回合日志（调试用）
```

---

## 五、各场景路由

| 场景 | 推荐模式 | 持久化 |
|------|----------|--------|
| **Feishu 私聊** (单人) | `Room` (SQLite) | `~/.histrategy/rooms/feishu-{user_id}/game.db` |
| **Feishu 群聊** (多人) | `Room` (SQLite) + 回合协调 | `~/.histrategy/rooms/feishu-group-{chat_id}/game.db` |
| **OpenClaw IM** | `Room` (SQLite) | `~/.histrategy/rooms/openclaw-{chat_id}/game.db` |
| **Hermes Agent** | `GameSessionManager` (SQLite) | `~/.histrategy/sessions/hermes/{chat_id}/game.db` |
| **Web UI** (浏览器多人) | `ServerClient` (HTTP) | PostgreSQL |
| **CLI** (`histrategy --dev`) | `DirectEngine` | `~/.histrategy/world_v2.json` （当前实现） |
| **E2E 测试** | `DirectEngine` | tmp path |

---

## 六、当前主要技术债：`room_manager.py` 内存缓存

> **[审阅意见]** `room_manager.py` 中存在内存 `dict` 缓存 `_rooms: dict[str, GameRoom]`。这意味着服务器重启后所有内存中的 GameRoom 丢失，只能从 DB 重建。但重建逻辑目前不完整（`GameRoom.save()`/`load()` 只实现了部分字段）。
>
> **这是比持久化模式选择更紧迫的技术债务**，需要在重构 Phase 4 中处理：
> - 去掉内存 dict，改为每次请求从 SQLite reload
> - 完成 `GameRoom.save()`/`load()` 的全字段序列化

---

## 七、迁移路径（如果当前用了 HTTP Server）

当前 `histrategy-agent` 已经使用 `GameSessionManager`（文件/SQLite 模式），不需要迁移。

如果未来需要从文件迁移到 Server 模式（例如加 Web UI 观察 IM 游戏），SDK 的 `Room` 和 `ServerClient` 共享相同的 `TurnResult` 类型，切换只需改初始化代码：

```python
# 文件模式 → Server 模式：只改一行
# room = Room("my-game", faction="shu")
client = ServerClient()
room = MultiplayerRoom.join(client, room_id, faction, token)
```

---

## 八、决策

**SDK+SQLite Reload 模式为 OpenClaw+Feishu 的主力持久化方案。**

理由：
1. 已实现且工作正常（`Room` + `GameSessionManager`）
2. 零运维成本，适合 Agent 的无状态调用模式
3. IM 场景不存在真正的并发问题，SQLite WAL 事务足够（比文件锁更健壮）
4. HTTP Server 保留给需要 Web UI + WebSocket 实时推送的 Web 客户端场景
5. 如果未来需要，从 SQLite 切换到 Server 的成本极低（SDK 抽象层统一接口）
