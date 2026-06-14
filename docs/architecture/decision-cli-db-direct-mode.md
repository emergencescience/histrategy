# Architecture Decision: CLI+DB Direct Mode

> **ADR-001** | 状态: Accepted | 日期: 2026-06-14
> 
> **决策**: histrategy 从"服务模式"迁移到"CLI+DB 直连模式"作为主要使用方式。
> 玩家 `pip install histrategy` → 设置 `HISTRATEGY_DATABASE_URL` → 直接操作 PostgreSQL。
> 无需维护服务进程。FastAPI Server 降级为可选 Web 适配层。

---

## 0. 决策摘要

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 主模式 | **CLI+DB 直连** | 游戏本质是回合制策略，不需要持续运行的服务进程 |
| 数据库 | **SQLite (本地) / PostgreSQL (远程)** | 已有成熟 DB 层，SQLite 零安装，PG 支持多人 |
| 服务器 | **降级为可选 Web 适配层** | 浏览器无法直连 DB，需 HTTP 桥接；CLI/Agent 不需要 |
| SDK | **histrategy-sdk 改为 thin DB wrapper** | 不再通过 HTTP 中继，直接调 Engine+DB |
| Multiplayer | **共享 PostgreSQL + 轮询 decision 表** | 所有玩家写 decision 到 DB，轮询等待全员提交 |
| Agent 客户端 | **直连 Engine+DB，跳过 HTTP** | 飞书/OpenClaw bot 本地跑 histrategy-engine，直接读写 PG |

---

## 1. 背景

### 1.1 当前架构

```
┌──────────────────────────────────────────────────┐
│                histrategy 部署拓扑                  │
│                                                    │
│  CLI (本地)           Web (浏览器)      Agent (飞书) │
│  histrategy --dev     浏览器           bot 进程      │
│       │                  │                │         │
│       │                  ▼                │         │
│       │          emergence.science        │         │
│       │          /games/histrategy        │         │
│       │                  │                │         │
│       │                  ▼                ▼         │
│       │         ┌────────────────┐  ┌──────────┐   │
│       │         │  orchestrator  │  │ SDK/HTTP │   │
│       │         │  (Nginx proxy) │  │ client   │   │
│       │         └───────┬────────┘  └────┬─────┘   │
│       │                 │                │         │
│       ▼                 ▼                ▼         │
│  ┌─────────┐    ┌─────────────────────────────┐    │
│  │ JSON 文件│    │  histrategy Server (FastAPI) │    │
│  │ ~/.hist │    │  Railway / :8080             │    │
│  │ rategy/ │    │  - room_manager (内存 dict)  │    │
│  └─────────┘    │  - single_player API         │    │
│                 │  - multiplayer API            │    │
│                 └──────────────┬──────────────┘    │
│                                │                    │
│                                ▼                    │
│                 ┌──────────────────────┐           │
│                 │  PostgreSQL (Railway)│           │
│                 │  或 SQLite (本地)     │           │
│                 └──────────────────────┘           │
└──────────────────────────────────────────────────┘
```

### 1.2 问题

| # | 问题 | 影响 |
|---|------|------|
| 1 | **两套持久化路径**: CLI 写 JSON 文件，Server 写 DB | 数据不一致，切换路径时丢失进度 |
| 2 | **Server 维护负担**: Railway 部署、uptime 监控、内存泄漏（`_rooms` dict） | DevOps 开销大，不符合"pip install 即玩"愿景 |
| 3 | **SDK 多一跳**: Agent → HTTP → Server → DB，而非 Agent → DB | 延迟增加，故障点多 |
| 4 | **room_manager 内存 dict**: 服务重启丢失所有活跃房间 | 不可靠的多人状态 |
| 5 | **Server 并非必需**: 游戏是回合制策略，不需要长连接或实时推送 | 架构过度设计 |

---

## 2. 目标架构

```
┌──────────────────────────────────────────────────┐
│           histrategy CLI+DB 直连架构               │
│                                                    │
│  CLI (本地)         Web (浏览器)      Agent (飞书)  │
│  histrategy play    浏览器           bot 进程       │
│       │                 │                │          │
│       │                 │ (可选)          │          │
│       │                 ▼                │          │
│       │          FastAPI Server           │          │
│       │          (thin web adapter)       │          │
│       │                 │                │          │
│       ▼                 ▼                ▼          │
│  ┌─────────────────────────────────────────────┐   │
│  │         histrategy-engine + DB layer        │   │
│  │  - GameEngine / GameRoom / TurnController   │   │
│  │  - db.connection (SQLite / PG auto-detect)  │   │
│  │  - db.models (save/load 全部走 SQL)         │   │
│  └──────────────────────┬──────────────────────┘   │
│                         │                          │
│                         ▼                          │
│              ┌──────────────────┐                  │
│              │   PostgreSQL      │                  │
│              │   (共享/远程)      │                  │
│              │   或 SQLite (本地) │                  │
│              └──────────────────┘                  │
└──────────────────────────────────────────────────┘
```

**核心变化**:
- CLI、Agent、Server 三者共享同一个 DB 层（`histrategy/db/`）
- Server 退化为 Web 浏览器的薄适配层（浏览器无法直连 DB）
- CLI 和 Agent 直接操作 Engine+DB，不走 HTTP
- Multiplayer 通过共享 PG 实现（所有玩家读写同一张 decision 表）

---

## 3. 详细分析

### 3.1 CLI 直连 DB

**当前**: `histrategy --dev` → GameEngine → JSON 文件 (`~/.histrategy/`)

**目标**: `histrategy play` → GameEngine → DB (`sqlite:///~/.histrategy/histrategy.db` 或 `postgresql://...`)

```bash
# 本地单人（默认 SQLite，零配置）
histrategy play --faction shu

# 远程多人（设置 PG URL）
export HISTRATEGY_DATABASE_URL=postgresql://...
histrategy play --faction shu --room abc123
```

**收益**:
- 单人/多人使用同一代码路径
- 存档自动持久化到 DB，不依赖文件系统
- 切换设备：改 `HISTRATEGY_DATABASE_URL` 指向同一 PG 即可

### 3.2 Agent 客户端直连

**当前**: Agent SDK → HTTP → histrategy Server → DB

**目标**: Agent SDK → histrategy-engine + DB（同进程）

```python
# histrategy-agent 内部
from histrategy.engine.game_room import GameRoom
from histrategy.db.models import save_room, load_room

room = load_room(room_id)
result = room.play_turn(faction_id, decision)
save_room(room)
```

**收益**:
- 零网络延迟（同进程调用）
- 无 Server 依赖（bot 进程自带完整引擎）
- 飞书/OpenClaw/Discord bot 统一代码路径

### 3.3 Multiplayer 通过共享 DB

**当前**: Server 内存 dict (`_rooms`, `_players`) + HTTP 轮询

**目标**: 所有玩家直连同一个 PG，通过 DB 行级锁协调

```
Player A (CLI) ──write──▶ decision table (PG) ◀──poll── Player B (CLI)
                                  │
                          all decisions in?
                                  │
                                  ▼
                         resolve_quarter()
                                  │
                                  ▼
                         write results → turn_summaries
```

**收益**:
- 无单点故障（PG 自带 HA）
- 决策持久化（玩家断线重连不丢决策）
- 天然支持异步（玩家可以在不同时间提交决策）

### 3.4 Server 降级为 Web Adapter

**保留 Server 的唯一原因**: 浏览器不能直连 PostgreSQL。

Server 变为 100-200 行的 thin adapter：
```python
# 唯一职责：HTTP ↔ DB 桥接
@app.post("/api/rooms/{room_id}/decisions")
async def submit_decision(room_id: str, req: DecisionRequest):
    room = load_room(room_id)
    result = room.play_turn(req.faction_id, req.decision)
    save_room(room)
    return result
```

**移除**:
- `room_manager.py` 内存 dict（全部走 DB）
- `single_player.py`（CLI 和 Agent 直连，Web 复用 room 系统）
- `persistence.py` + `persistence_adapter.py`（DB 层已统一）
- 复杂的 orchestrator 集成代码

---

## 4. 迁移计划

### Phase 1: DB 层完备化（1-2h）

- [ ] `GameEngine` 增加 `save_to_db()` / `load_from_db()` 方法
- [ ] CLI `histrategy play` 默认使用 SQLite（`~/.histrategy/histrategy.db`）
- [ ] 兼容旧 JSON 存档自动迁移

### Phase 2: Server 瘦身（1-2h）

- [ ] 移除 `room_manager.py` 内存 dict
- [ ] 移除 `single_player.py`（复用 room 系统）
- [ ] 简化为 thin web adapter（~200行）
- [ ] 测试: 现有 Web 客户端零破坏

### Phase 3: SDK 直连（1h）

- [ ] `histrategy-sdk` 改为 import `histrategy.engine` + `histrategy.db`
- [ ] 移除 HTTP 调用，改为本地函数调用
- [ ] 向后兼容：保留 HTTP fallback（`HISTRATEGY_REMOTE_URL`）

### Phase 4: Agent 客户端切换（1h）

- [ ] `histrategy-agent` 改用 SDK 直连模式
- [ ] 飞书 bot 验证

---

## 5. 风险与缓解

| 风险 | 缓解 |
|------|------|
| **PG 连接数**: 每个 CLI/Agent 进程一个连接 | 默认 SQLite（零连接开销）；PG 用 connection pooler |
| **DB schema 迁移**: CLI 用户需要更新 DB | `init_db()` 已支持幂等迁移；SQLite 自动创建 |
| **Web 客户端仍需 Server**: Server 不能完全删除 | Server 降级为 200 行 thin adapter，维护成本极低 |
| **Multiplayer 并发**: 多玩家同时写 decision 表 | 使用 PG row-level lock / `INSERT ... ON CONFLICT` |
| **向后兼容**: 现有 SDK 用户依赖 HTTP API | 保留 `/api/` 路由作为 deprecated 兼容层 |

---

## 6. 不做什么

- ❌ 不删除 Server（Web 客户端需要）
- ❌ 不删除 SDK HTTP 模式（向后兼容 1-2 版本）
- ❌ 不强制 PG（SQLite 仍然是默认本地模式）
- ❌ 不改变 Engine 接口（GameEngine / GameRoom API 不变）

---

## 7. 成功标准

1. `pip install histrategy && histrategy play --faction shu` 即可开始游戏（零配置）
2. CLI 进度自动保存到 DB，重启后恢复
3. 设置 `HISTRATEGY_DATABASE_URL` 后多人可共享同一 PG 游戏
4. 现有 Web 客户端行为不变
5. 测试套件全部通过
