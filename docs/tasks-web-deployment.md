# 三國志略 Web 部署任务书 (v1.0 单机版)

> **目标**: 让玩家在 https://emergence.science 注册即玩，存档持久化到 PostgreSQL，LLM 优先使用用户自带 DeepSeek API Key。
>
> **日期**: 2026-06-09
>
> **涉及仓库**:
> - `histrategy` → `/Users/julian/gitbubble/histrategy`
> - `orchestrator` → `/Users/julian/gitbubble/emergence/apps/orchestrator`
> - `surprisal-portal` → `/Users/julian/gitbubble/emergence/apps/surprisal-portal`
>
> **AI Agent 执行规则**:
> - 按 Phase 顺序执行，每 Task 完成后运行验证命令，通过后再继续
> - 每个 Task 完成提交一次 Commit（`git commit -m "feat: task X.Y ..."`）
> - **不要一次性写完多个 Task**

---

## 架构约定

| 组件 | 地址 | 备注 |
|------|------|------|
| 玩家游戏 API | `https://api.emergence.science/games/histrategy/*` | 挂载到 Orchestrator |
| 存档数据库 | PostgreSQL (Railway, 已有 Orchestrator DB) | 新增 2 张表 |
| 前端游戏页面 | `https://emergence.science/games/histrategy` | surprisal-portal 新增路由 |
| JWT 共享 | `JWT_SECRET` 环境变量（两端相同） | HS256，已有 Orchestrator 实现 |
| LLM | DeepSeek-v4-pro（用户自带 Key）| Key 仅在请求生命周期内存在，不落库 |

---

## Phase B：Orchestrator 存档接口（先做，其他两端依赖它）

**仓库**: `emergence/apps/orchestrator`

---

### Task B.1: 新增游戏存档数据模型

**目标文件**: `core/models.py`

**任务描述**:

在 `core/models.py` 末尾追加以下两个 SQLModel 表（不修改任何现有模型）：

```python
class GameSession(SQLModel, table=True):
    """一个用户的一局游戏会话（存档元信息）。"""
    __table_args__ = ({"extend_existing": True},)
    __tablename__ = "gamesession"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True, sa_type=PG_UUID(as_uuid=True))
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True, sa_type=PG_UUID(as_uuid=True))
    game_title: str = Field(default="三國志略")        # 供未来扩展多游戏
    scenario: str = Field(default="207")              # "207" | "190" 等
    faction: str = Field(default="shu")              # "shu" | "cao" | "wu"
    turn: int = Field(default=1)
    year: int = Field(default=207)
    season: str = Field(default="春")
    is_completed: bool = Field(default=False)
    session_metadata: dict = Field(default_factory=dict, sa_column=sa.Column(sa.JSON))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )


class GameSave(SQLModel, table=True):
    """游戏存档快照（存档槽位，最多 4 个：slot 0=自动，1-3=手动）。"""
    __table_args__ = (
        sa.UniqueConstraint("session_id", "slot", name="uq_gamesave_session_slot"),
        {"extend_existing": True},
    )
    __tablename__ = "gamesave"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True, sa_type=PG_UUID(as_uuid=True))
    session_id: uuid.UUID = Field(foreign_key="gamesession.id", index=True, sa_type=PG_UUID(as_uuid=True))
    slot: int = Field(default=0)          # 0=autosave, 1-3=manual
    world_state: dict = Field(default_factory=dict, sa_column=sa.Column(sa.JSON))
    turn: int = Field(default=1)
    year: int = Field(default=207)
    season: str = Field(default="春")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
```

**验证**:
```bash
cd /Users/julian/gitbubble/emergence/apps/orchestrator
python -c "from core.models import GameSession, GameSave; print('OK')"
```

---

### Task B.2: 数据库迁移（新增两张表）

**目标文件**: `core/migrations.py` 和 `core/database.py`

**任务描述**:

1. 在 `migrations.py` 末尾追加函数 `migrate_game_tables(engine)`：

```python
def migrate_game_tables(engine: Engine) -> None:
    """Create gamesession and gamesave tables if they don't exist.

    SQLModel.metadata.create_all() handles new tables automatically,
    but this function ensures idempotency for column-level changes on PostgreSQL.
    """
    dialect = engine.dialect.name
    if dialect != "postgresql":
        logger.info("Skipping game tables migration — not PostgreSQL")
        return

    with engine.connect() as conn:
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        if "gamesession" not in tables:
            logger.info("gamesession table will be created by SQLModel.create_all()")
        else:
            logger.info("gamesession table already exists — skipping")

        if "gamesave" not in tables:
            logger.info("gamesave table will be created by SQLModel.create_all()")
        else:
            logger.info("gamesave table already exists — skipping")

        conn.commit()
    logger.info("Game tables migration check complete")
```

2. 在 `migrations.py` 的 `run_migrations()` 函数末尾追加调用：
```python
    migrate_game_tables(engine)
```

3. 在 `core/database.py` 的 `create_db_and_tables()` 中，确保 `GameSession` 和 `GameSave` 已被 import（触发 SQLModel.metadata 注册）。在 `create_db_and_tables` 函数顶部加：
```python
    from core.models import GameSession, GameSave  # noqa: F401 — register tables
```

**验证**:
```bash
cd /Users/julian/gitbubble/emergence/apps/orchestrator
python -c "
from core.database import create_db_and_tables
create_db_and_tables()
print('Tables created OK')
"
```
预期输出：`Tables created OK`（本地 SQLite 模式）

---

### Task B.3: 游戏存档路由

**目标文件**: `routes/games.py` [NEW]

**任务描述**:

创建 `/Users/julian/gitbubble/emergence/apps/orchestrator/routes/games.py`，实现以下 5 个端点：

```python
"""
游戏存档路由 — /games/histrategy/*

认证：所有端点需要 Bearer JWT（与 Orchestrator /auth 共用 JWT_SECRET）。
存档规则：每用户每局游戏最多 4 个槽位（slot 0=自动，1-3=手动）。
"""
```

端点列表：

| Method | Path | 说明 |
|--------|------|------|
| `POST` | `/games/histrategy/sessions` | 创建新游戏会话，返回 `session_id` |
| `GET` | `/games/histrategy/sessions` | 列出当前用户所有会话（分页，默认最新 20 条） |
| `GET` | `/games/histrategy/sessions/{session_id}` | 获取会话详情（含最新存档元信息） |
| `PUT` | `/games/histrategy/sessions/{session_id}/save` | 更新存档（Body: `{slot: int, world_state: dict, turn: int, year: int, season: str}`） |
| `DELETE` | `/games/histrategy/sessions/{session_id}` | 软删除（设置 `is_completed=True`），不物理删除 |

**认证实现**: 复用 `core/auth_jwt.py` 的 `decode_jwt`，从 `Authorization: Bearer <token>` 提取 `user_id`。如果 token 无效，返回 `401`。

**约束**:
- `PUT .../save` 时，若 slot 已存在则覆写（UPSERT），不新建行
- 返回的 `world_state` 字段可能很大（最多 200KB），接口正常返回即可，不截断
- `DELETE` 时，如果 `session_id` 不属于当前用户，返回 `403`

**验证**:
```bash
cd /Users/julian/gitbubble/emergence/apps/orchestrator
python -c "from routes.games import router; print('routes/games.py OK')"
```

---

### Task B.4: 注册路由到 Orchestrator main.py

**目标文件**: `main.py`

**任务描述**:

在 `main.py` 中：

1. 在 import 区追加：
```python
from routes import games
```

2. 在 `app.include_router(seo.router)` 之后追加：
```python
app.include_router(games.router)
```

**验证**:
```bash
cd /Users/julian/gitbubble/emergence/apps/orchestrator
python -c "from main import app; routes = [r.path for r in app.routes]; assert any('games' in r for r in routes), 'games routes not found'; print('main.py OK')"
```

---

### Task B.5: 编写 Orchestrator 存档路由测试

**目标文件**: `tests/test_games_routes.py` [NEW]

**任务描述**:

使用 FastAPI `TestClient` 编写集成测试（SQLite 内存模式）：

```python
# 测试场景：
# 1. test_create_session — 创建会话返回 session_id，HTTP 200
# 2. test_list_sessions_empty — 新用户返回空列表
# 3. test_save_and_load_slot_0 — autosave 写入 slot 0，读回 world_state 一致
# 4. test_save_slot_upsert — 同一 slot 写入两次，第二次覆写不报错
# 5. test_save_slots_1_to_3 — 手动存档 slot 1-3 全部可写
# 6. test_delete_session — 删除后 is_completed=True
# 7. test_unauthorized_delete — 用 user A 的 token 删 user B 的 session，返回 403
```

**验证**:
```bash
cd /Users/julian/gitbubble/emergence/apps/orchestrator
pytest tests/test_games_routes.py -v
```
预期：7/7 通过

---

## Phase A：Histrategy Server 接入认证与持久化

**仓库**: `histrategy`

---

### Task A.1: 新增认证中间件

**目标文件**: `histrategy/server/auth.py` [NEW]

**任务描述**:

创建 `/Users/julian/gitbubble/histrategy/histrategy/server/auth.py`：

```python
"""
JWT Auth middleware for Histrategy Server.

Verifies tokens signed by Orchestrator (shared JWT_SECRET).
Extracts user_id from token's 'sub' claim.
"""
import os
from typing import Optional

import jwt
from fastapi import Header, HTTPException, status

JWT_SECRET = os.environ.get("JWT_SECRET", "emergence-secret-dev")
JWT_ALGORITHM = "HS256"


def get_current_user_id(authorization: Optional[str] = Header(default=None)) -> str:
    """FastAPI dependency: extract user_id from Bearer JWT.

    Returns the user UUID string from 'sub' claim.
    Raises 401 if token is missing or invalid.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )
    token = authorization[len("Bearer "):]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token missing 'sub' claim")
        return str(user_id)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
```

**验证**:
```bash
cd /Users/julian/gitbubble/histrategy
python -c "from histrategy.server.auth import get_current_user_id; print('auth.py OK')"
```

---

### Task A.2: 新增持久化客户端（调用 Orchestrator 存档 API）

**目标文件**: `histrategy/server/persistence.py` [NEW]

**任务描述**:

创建 `/Users/julian/gitbubble/histrategy/histrategy/server/persistence.py`：

```python
"""
Persistence client — wraps Orchestrator /games/histrategy/* endpoints.

All methods are synchronous (httpx). Called from FastAPI route handlers.
ORCHESTRATOR_URL default: https://api.emergence.science
"""
import os
from typing import Optional
import httpx

ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "https://api.emergence.science").rstrip("/")
_TIMEOUT = 10.0  # seconds


def _headers(jwt_token: str) -> dict:
    return {"Authorization": f"Bearer {jwt_token}", "Content-Type": "application/json"}


def create_session(jwt_token: str, scenario: str, faction: str) -> dict:
    """POST /games/histrategy/sessions → {session_id, ...}"""
    r = httpx.post(
        f"{ORCHESTRATOR_URL}/games/histrategy/sessions",
        json={"scenario": scenario, "faction": faction},
        headers=_headers(jwt_token),
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def list_sessions(jwt_token: str) -> list[dict]:
    """GET /games/histrategy/sessions → [{session_id, ...}, ...]"""
    r = httpx.get(
        f"{ORCHESTRATOR_URL}/games/histrategy/sessions",
        headers=_headers(jwt_token),
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    return r.json().get("sessions", [])


def save_game(jwt_token: str, session_id: str, slot: int,
              world_state: dict, turn: int, year: int, season: str) -> dict:
    """PUT /games/histrategy/sessions/{session_id}/save → {ok: true}"""
    r = httpx.put(
        f"{ORCHESTRATOR_URL}/games/histrategy/sessions/{session_id}/save",
        json={"slot": slot, "world_state": world_state,
              "turn": turn, "year": year, "season": season},
        headers=_headers(jwt_token),
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def load_game(jwt_token: str, session_id: str) -> Optional[dict]:
    """GET /games/histrategy/sessions/{session_id} → session detail with latest save"""
    r = httpx.get(
        f"{ORCHESTRATOR_URL}/games/histrategy/sessions/{session_id}",
        headers=_headers(jwt_token),
        timeout=_TIMEOUT,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()
```

**验证**:
```bash
cd /Users/julian/gitbubble/histrategy
python -c "from histrategy.server.persistence import create_session, save_game; print('persistence.py OK')"
```

---

### Task A.3: 改造 api.py — 支持 JWT 认证与持久化存档

**目标文件**: `histrategy/server/api.py`

**任务描述**:

在现有 `api.py` 的 `create_app()` 函数中，做以下 **4 处改动**（不要大幅重写）：

**改动 1**: 在函数顶部引入依赖（在 `from fastapi import FastAPI` 之后）：
```python
from fastapi import Depends, FastAPI, Header
from histrategy.server.auth import get_current_user_id
```

**改动 2**: 修改 `POST /api/games` 端点，接受可选 JWT（用于绑定到 Orchestrator session）和 DeepSeek API Key：

```python
# 新增 Request Body 字段（在 CreateGameRequest 中追加）
class CreateGameRequest(BaseModel):
    faction: str = "shu"
    scenario: str = "207"
    new: bool = True
    session_id: str | None = None      # 新增：Orchestrator session ID
    llm_api_key: str | None = None     # 新增：用户自带 DeepSeek API Key（不落库）
```

**改动 3**: 在 `POST /api/games` 路由处理函数签名中，追加可选认证 Header：
```python
@app.post("/api/games")
def create_game(req: CreateGameRequest,
                authorization: str | None = Header(default=None)):
```
在函数体内，如果 `req.llm_api_key` 不为空，则设置环境变量 `os.environ["DEEPSEEK_API_KEY"] = req.llm_api_key`（仅对本次请求的 LLMAdapter 生效，因为 LLMAdapter 在 `_get_or_create_engine` 内即时读取 env）。将 `session_id` 存入 `_games` dict 的元数据（使用 `_game_meta: dict[str, dict]` 全局字典）。

**改动 4**: 新增 `POST /api/games/{game_id}/autosave` 端点：
```python
@app.post("/api/games/{game_id}/autosave")
def autosave_game(game_id: str, authorization: str | None = Header(default=None)):
    """
    自动存档：将当前游戏状态序列化，通过 Orchestrator API 持久化到 slot 0。
    需要 Authorization Bearer JWT。
    如未配置 ORCHESTRATOR_URL 或无 JWT，返回 {"ok": false, "reason": "..."}（不报错，降级处理）。
    """
```

**验证**:
```bash
cd /Users/julian/gitbubble/histrategy
python -c "
from histrategy.server.api import create_app
app = create_app()
routes = [r.path for r in app.routes]
assert '/api/games/{game_id}/autosave' in routes, 'autosave route missing'
print('api.py改造 OK, routes:', [r for r in routes if 'game' in r])
"
```

---

### Task A.4: 新增 Railway 部署配置

**目标文件**: `railway.toml` [NEW] 和 `Procfile` [NEW]（均在 histrategy 根目录）

**`railway.toml`**:
```toml
[build]
  builder = "nixpacks"

[deploy]
  startCommand = "uvicorn histrategy.server.api:app --host 0.0.0.0 --port $PORT"
  healthcheckPath = "/api/health"
  healthcheckTimeout = 30

[environments.production.variables]
  HISTRATEGY_DATA_DIR = "/tmp/histrategy"
  LLM_MODEL = "deepseek-v4-pro"
```

**`Procfile`**:
```
web: uvicorn histrategy.server.api:app --host 0.0.0.0 --port $PORT
```

> **注**: `JWT_SECRET`、`ORCHESTRATOR_URL` 需要在 Railway Service Variables 手动设置。

**验证**:
```bash
cd /Users/julian/gitbubble/histrategy
cat railway.toml && cat Procfile && echo "部署配置文件 OK"
```

---

### Task A.5: 更新 CORS 配置

**目标文件**: `histrategy/server/api.py`

**任务描述**:

将 `create_app()` 中的 CORS 配置从 `allow_origins=["*"]` 改为：

```python
import os as _os

_cors_origins = [
    "http://localhost:3000",
    "https://emergence.science",
    "https://www.emergence.science",
    "https://surprisal-portal.vercel.app",
]
# Allow extra origins from env (comma-separated)
_extra = _os.environ.get("ALLOWED_ORIGINS", "")
if _extra:
    _cors_origins.extend([o.strip() for o in _extra.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**验证**:
```bash
cd /Users/julian/gitbubble/histrategy
python -c "
from histrategy.server.api import create_app
app = create_app()
from fastapi.middleware.cors import CORSMiddleware
mw = [m for m in app.middleware_stack.middleware if hasattr(m, 'allow_origins')]
print('CORS configured')
"
```

---

### Task A.6: 更新 Histrategy Server 测试

**目标文件**: `tests/test_server.py`

**任务描述**:

在现有 `tests/test_server.py` 末尾追加新测试类（不修改已有测试）：

```python
class TestAuthAndPersistence:
    """Tests for JWT auth and autosave endpoint."""

    def test_autosave_without_jwt_returns_degraded(self, client):
        """Autosave without JWT should return ok=false gracefully, not 401."""
        create_resp = client.post("/api/games", json={"faction": "shu"})
        game_id = create_resp.json()["game_id"]
        resp = client.post(f"/api/games/{game_id}/autosave")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "reason" in data

    def test_create_game_with_llm_api_key(self, client):
        """llm_api_key in body is accepted and sets env for LLM (not stored)."""
        resp = client.post("/api/games", json={
            "faction": "shu",
            "llm_api_key": "sk-test-key-1234567890",
        })
        assert resp.status_code == 200
        assert "game_id" in resp.json()

    def test_create_game_with_session_id(self, client):
        """session_id in body is accepted and stored in game meta."""
        resp = client.post("/api/games", json={
            "faction": "shu",
            "session_id": "test-session-uuid-1234",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "game_id" in data
```

**验证**:
```bash
cd /Users/julian/gitbubble/histrategy
pytest tests/test_server.py -v
```
预期：原有测试 + 3 个新测试全部通过

---

## Phase C：Web 前端游戏页面

**仓库**: `emergence/apps/surprisal-portal`

---

### Task C.1: 游戏入口页

**目标文件**: `src/app/[lang]/games/histrategy/page.tsx` [NEW]

**任务描述**:

创建游戏大厅页面。布局：
- **顶部**: 游戏标题"三國志略"（毛笔字风格，红金配色），副标题"AI 驱动的三国策略沙盘"
- **中部**: 三个阵营选择卡片（蜀/魏/吴），各含一句简介，点击高亮选中
- **底部左**: "继续游戏"按钮（加载已有存档列表，无存档时灰色禁用）
- **底部右**: "开始新游戏"按钮（调用 Orchestrator 创建 session，跳转到 /games/histrategy/play/[sessionId]）
- **Key 输入框**: 折叠面板"⚙️ LLM 设置"，展开后有 DeepSeek API Key 输入框，说明文字"您的 Key 仅用于本次游戏，不会被存储到服务器"，Key 存入 `sessionStorage`

**API 调用**:
- `POST /games/histrategy/sessions`（到 Orchestrator，需要 JWT cookie）
- `GET /games/histrategy/sessions`（列出已有存档）

**验证**: 在浏览器中访问 `http://localhost:3000/zh/games/histrategy`，能看到三个阵营卡片，页面无 console error。

---

### Task C.2: 主游戏界面

**目标文件**: `src/app/[lang]/games/histrategy/play/[sessionId]/page.tsx` [NEW]

**任务描述**:

创建主游戏界面（参考 `histrategy/histrategy/web/index.html` 的布局，用 React/TSX 重写）。

**界面布局（三栏）**:
```
┌──────────────────────────────────────────────────────────────┐
│  左侧（势力状态）  │  中间（叙事区域）  │  右侧（地图/资源） │
│  - 阵营名、年份季节  │  - 谋士朝议文字   │  - 领土列表       │
│  - 兵力/粮草/金钱   │  - 历史指令记录   │  - NPC动向        │
│  - 存档/读档按钮   │  - 玩家输入框     │  - 赛季小结       │
└──────────────────────────────────────────────────────────────┘
```

**核心逻辑**:
1. 页面加载时：先调用 `GET /games/histrategy/sessions/{sessionId}` 获取存档
2. 若有 `world_state`：向 Histrategy Server `POST /api/games`（带 `session_id`、`llm_api_key`），恢复游戏状态
3. 新游戏：直接 `POST /api/games`
4. 每次回合结束（`POST /api/games/{id}/command` 返回后），调用 Histrategy Server `POST /api/games/{id}/autosave` 自动存档到 slot 0

**Histrategy Server URL**: 从环境变量 `NEXT_PUBLIC_HISTRATEGY_SERVER_URL` 读取（开发默认 `http://localhost:8080`，生产 `https://api.emergence.science/games/histrategy`）

> **注**: Histrategy Server 部署后，Orchestrator 会反向代理 `/games/histrategy/*` → Histrategy Server（见 Task D.1）

**验证**: 访问 `http://localhost:3000/zh/games/histrategy/play/test-session`，界面正常渲染，无 console error（可以用 mock data）。

---

### Task C.3: 游戏 API Hook（前端工具函数）

**目标文件**: `src/lib/histrategy-api.ts` [NEW]

**任务描述**:

封装所有 Histrategy Server 调用，供游戏页面使用：

```typescript
// 所有函数都接收可选的 llmApiKey，透传给 Histrategy Server
export async function createGame(faction: string, scenario: string, sessionId?: string, llmApiKey?: string): Promise<GameCreatedResponse>
export async function getPlan(gameId: string, serverUrl: string): Promise<PlanResponse>
export async function executeCommand(gameId: string, decision: string, serverUrl: string): Promise<CommandResponse>
export async function autosave(gameId: string, serverUrl: string, jwtToken: string): Promise<{ok: boolean}>

// 类型定义（对应 histrategy/server/api.py 的响应结构）
export interface FactionStatus { name: string; strength: number; food: number; treasury: number; ... }
export interface PlanResponse { court_dialogue: string; suggestions: string[]; faction_status: FactionStatus; ... }
export interface CommandResponse { narrative: string; aftermath: string; state_changes: Record<string,number>; game_over: null | {...}; ... }
```

**验证**:
```bash
cd /Users/julian/gitbubble/emergence/apps/surprisal-portal
npx tsc --noEmit
```
预期：无 TypeScript 错误

---

### Task C.4: 在首页添加游戏入口

**目标文件**: `src/app/[lang]/page.tsx` 或相关的首页组件

**任务描述**:

在 emergence.science 首页（找到首页的主要内容区）添加一个游戏入口卡片，样式与现有卡片统一：

```tsx
<GameCard
  title="三國志略"
  titleEn="Histrategy"
  description="AI 驱动的三国志策略游戏。你来做决策，LLM 扮演谋士与历史。"
  href={`/${lang}/games/histrategy`}
  badge="Beta"
  icon="⚔️"
/>
```

如果 `GameCard` 组件不存在，直接用 `<a>` + 现有 CSS 类实现，保持风格统一。

**验证**: 访问 `http://localhost:3000`，首页能看到"三國志略"入口，点击跳转正常。

---

### Task C.5: 环境变量配置

**目标文件**: `emergence/apps/surprisal-portal/.env.local`（追加，不覆盖）

**任务描述**:

追加以下环境变量（仅供本地开发）：

```bash
# Histrategy Game Server (local dev)
NEXT_PUBLIC_HISTRATEGY_SERVER_URL=http://localhost:8080
```

同时在 `README.md` 中追加说明（开发者文档）：

```markdown
## 游戏服务配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `NEXT_PUBLIC_HISTRATEGY_SERVER_URL` | `http://localhost:8080` | Histrategy 游戏服务地址 |
```

**验证**:
```bash
grep "HISTRATEGY" /Users/julian/gitbubble/emergence/apps/surprisal-portal/.env.local
```

---

## Phase D：部署配置

### Task D.1: Orchestrator 反向代理 Histrategy Server

**目标文件**: `emergence/apps/orchestrator/routes/games.py`（在 Task B.3 基础上追加）

**任务描述**:

在 `routes/games.py` 中追加一个**反向代理路由**，将 `/games/histrategy/api/*` 转发到 Histrategy Server：

```python
HISTRATEGY_SERVER_URL = os.environ.get("HISTRATEGY_SERVER_URL", "http://localhost:8080")

@router.api_route(
    "/games/histrategy/api/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE"],
    include_in_schema=False,
)
async def proxy_to_histrategy(path: str, request: Request):
    """
    反向代理：将 /games/histrategy/api/* → Histrategy Server /api/*
    透传所有 Headers（含 Authorization）和 Body。
    """
    import httpx
    target_url = f"{HISTRATEGY_SERVER_URL}/api/{path}"
    body = await request.body()
    headers = dict(request.headers)
    headers.pop("host", None)

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body,
            params=dict(request.query_params),
        )

    from fastapi.responses import Response
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=dict(resp.headers),
    )
```

这样，前端只需访问 `https://api.emergence.science/games/histrategy/api/games` 即可（无需暴露 Histrategy Server 地址）。

**验证**:
```bash
cd /Users/julian/gitbubble/emergence/apps/orchestrator
python -c "
from routes.games import router
proxy_routes = [r.path for r in router.routes if 'proxy' in r.name]
print('Proxy routes:', proxy_routes)
"
```

---

### Task D.2: Railway 环境变量文档

**目标文件**: `histrategy/docs/deployment-railway.md` [NEW]

**任务描述**:

创建部署文档，列出 Histrategy Server（新建 Railway Service）需要配置的环境变量：

```markdown
# Histrategy Server — Railway 部署指南

## 新建 Service

1. 在 Railway 项目中新建 Service，连接 histrategy GitHub 仓库
2. Railway 会自动读取 railway.toml 使用 Nixpacks 构建

## 必填环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `JWT_SECRET` | 与 Orchestrator 共享，值完全相同 | 从 Orchestrator Service 复制 |
| `ORCHESTRATOR_URL` | Orchestrator 生产地址 | `https://api.emergence.science` |

## 可选环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HISTRATEGY_DATA_DIR` | `/tmp/histrategy` | 临时文件存储（Railway 无持久化磁盘） |
| `LLM_MODEL` | `deepseek-v4-pro` | 默认 LLM 模型 |
| `ALLOWED_ORIGINS` | （空）| 追加 CORS 白名单，逗号分隔 |

## Orchestrator 端需要配置的变量

| 变量 | 说明 |
|------|------|
| `HISTRATEGY_SERVER_URL` | Histrategy Server 的 Railway 内网地址（同项目 Service 间可用 `http://histrategy.railway.internal:8080`）|
```

**验证**:
```bash
cat /Users/julian/gitbubble/histrategy/docs/deployment-railway.md
```

---

## 全链路集成验证（所有 Phase 完成后）

**在开发机上本地端对端测试**:

```bash
# 1. 启动 Orchestrator（本地 SQLite 模式）
cd /Users/julian/gitbubble/emergence/apps/orchestrator
uvicorn main:app --port 8000 --reload &

# 2. 启动 Histrategy Server
cd /Users/julian/gitbubble/histrategy
ORCHESTRATOR_URL=http://localhost:8000 \
JWT_SECRET=emergence-secret-dev \
uvicorn histrategy.server.api:app --port 8080 --reload &

# 3. 启动 surprisal-portal
cd /Users/julian/gitbubble/emergence/apps/surprisal-portal
NEXT_PUBLIC_HISTRATEGY_SERVER_URL=http://localhost:8000/games/histrategy/api \
npm run dev &

# 4. 获取测试 JWT（使用 Orchestrator 现有 /auth 注册流程获取，或手动生成）
python3 -c "
import jwt, datetime
token = jwt.encode(
    {'sub': 'test-user-id-1234', 'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7)},
    'emergence-secret-dev', algorithm='HS256'
)
print('TEST_JWT:', token)
"

# 5. 端对端测试（替换 <TOKEN> 为上一步输出的 JWT）
TEST_JWT="<TOKEN>"

# 5a. 在 Orchestrator 创建游戏会话
curl -s -X POST http://localhost:8000/games/histrategy/sessions \
  -H "Authorization: Bearer $TEST_JWT" \
  -H "Content-Type: application/json" \
  -d '{"scenario":"207","faction":"shu"}' | jq .

# 5b. 在 Histrategy Server 创建游戏
SESSION_ID="<从上面输出复制>"
curl -s -X POST http://localhost:8080/api/games \
  -H "Authorization: Bearer $TEST_JWT" \
  -H "Content-Type: application/json" \
  -d "{\"faction\":\"shu\",\"session_id\":\"$SESSION_ID\"}" | jq .

# 5c. 执行一个回合
GAME_ID="<从上面输出复制>"
curl -s -X POST http://localhost:8080/api/games/$GAME_ID/command \
  -H "Authorization: Bearer $TEST_JWT" \
  -H "Content-Type: application/json" \
  -d '{"decision":"发展农业，广积粮草"}' | jq .

# 5d. 触发自动存档
curl -s -X POST http://localhost:8080/api/games/$GAME_ID/autosave \
  -H "Authorization: Bearer $TEST_JWT" | jq .

# 5e. 从 Orchestrator 读取存档，验证 world_state 已持久化
curl -s http://localhost:8000/games/histrategy/sessions/$SESSION_ID \
  -H "Authorization: Bearer $TEST_JWT" | jq '.saves[0].turn'
```

**预期结果**:
- 步骤 5a 返回 `session_id`
- 步骤 5b 返回 `game_id`，`faction_status.is_active=true`
- 步骤 5c 返回 `narrative`，`turn >= 2`
- 步骤 5d 返回 `{ok: true}`
- 步骤 5e 返回 `turn` 值为 `2`（存档成功）

---

## 给 Hermes 的注意事项

> [!IMPORTANT]
> 1. **PyJWT 依赖**：`histrategy` 的 `pyproject.toml` 需要追加 `pyjwt>=2.8.0`。在 Task A.1 完成后检查并补充。
> 2. **httpx 依赖**：`histrategy` 已有 `httpx`（`llm/adapter.py` 使用），`persistence.py` 直接复用，无需追加依赖。
> 3. **LLM Key 安全**：`llm_api_key` 在 `POST /api/games` 接收后，设为临时 env var；在 `_get_or_create_engine` 创建 `LLMAdapter` 后，立即 `os.environ.pop("DEEPSEEK_API_KEY", None)` 清除，**不允许 key 在进程中长期存在**。
> 4. **WorldState 序列化**：调用 `engine.world_state_v2.to_dict()` 获取可 JSON 化的 dict，存入 `world_state` 字段。如果 `to_dict()` 不存在，先检查 `histrategy-engine/src/histrategy_engine/world/__init__.py`。
> 5. **测试隔离**：Orchestrator 测试使用 SQLite 内存数据库（`DATABASE_URL=sqlite:///:memory:`），不要依赖真实 PostgreSQL。
> 6. **Phase 顺序**：B → A → C → D。C 的 API 调用依赖 A 和 B 就绪。
