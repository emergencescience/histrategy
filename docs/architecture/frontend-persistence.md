# Histrategy Frontend + Persistence Architecture

## 现状

```
┌──────────────────────────────────┐
│  histrategy --serve (FastAPI)    │
│  ● 内嵌 HTML (web/index.html)    │
│  ● 持久化: JSON 文件 (~/.histrategy/) │
│  ● 无 PostgreSQL / 无 SQLite     │
└────────────┬─────────────────────┘
             │ HTTP (仅当 ORCHESTRATOR_URL 设置时)
┌────────────▼─────────────────────┐
│  emergence-orchestrator          │
│  ● PostgreSQL (gamesession/gamesave/gameturn) │
│  ● JWT auth, credit 扣费        │
└──────────────────────────────────┘
```

**问题**: 
- `histrategy/web/index.html` 是独立开发的 HTML+CSS+JS，与 `surprisal-portal` Next.js 前端代码完全不同
- 持久化层没有统一接口——本地 JSON 文件和远程 orchestrator 是两套代码路径
- 用户本地玩 (`histrategy --serve`) 和线上玩 (`emergence.science/play/histrategy`) 体验不一致

## 目标架构

```
┌──────────────────────────────────────────────────┐
│         统一前端 (histrategy/web/)                │
│  ● 单个 SPA — HTML+CSS+JS (无框架依赖)           │
│  ● 本地 serve 和线上 portal 共用同一套代码        │
│  ● 通过 Fetch API 调用后端 — 不关心后端是什么     │
└──────────────────┬───────────────────────────────┘
                   │ Fetch API (同域名)
┌──────────────────▼───────────────────────────────┐
│      histrategy server (FastAPI :8080)           │
│  ● 路由不变: /api/games, /api/games/{id}/command │
│  ● 引擎: GameEngine (现在 macro 模式)            │
│  ● 静态文件: 直接 serve web/ 目录                │
│  ● 持久化: PersistenceAdapter (统一接口)         │
└──────────────────┬───────────────────────────────┘
                   │
    ┌──────────────┴──────────────┐
    │                             │
┌───▼──────────────┐   ┌─────────▼──────────────┐
│ LocalFileAdapter │   │ OrchestratorAdapter    │
│ JSON 文件        │   │ HTTP → Postgres        │
│ ~/.histrategy/   │   │ emergence-orchestrator │
│ 无需 SQLite      │   │ JWT + credit 扣费      │
└──────────────────┘   └────────────────────────┘
```

## Adapter 接口设计

```python
from abc import ABC, abstractmethod

class PersistenceAdapter(ABC):
    """统一持久化接口 — 本地 JSON 和远程 PostgreSQL 共用"""

    @abstractmethod
    async def create_session(self, faction_id: str, scenario_id: str) -> str:
        """创建新游戏会话，返回 session_id"""
        ...

    @abstractmethod
    async def save_state(self, session_id: str, world_state: dict) -> None:
        """保存世界状态快照"""
        ...

    @abstractmethod
    async def load_state(self, session_id: str) -> dict | None:
        """加载世界状态快照"""
        ...

    @abstractmethod
    async def append_turn(self, session_id: str, turn_data: dict) -> None:
        """追加一回合的历史记录"""
        ...

    @abstractmethod
    async def list_sessions(self) -> list[dict]:
        """列出所有活跃会话"""
        ...


class LocalFileAdapter(PersistenceAdapter):
    """本地 JSON 文件存储
    
    存储结构: ~/.histrategy/sessions/{session_id}/
      ├── world_v2.json   # 世界状态
      └── turns.jsonl     # 回合历史 (JSONL)
    """
    def __init__(self, data_dir: str = "~/.histrategy"):
        self.data_dir = os.path.expanduser(data_dir)
    
    async def create_session(self, faction_id, scenario_id):
        sid = f"{faction_id}_{int(time.time())}"
        os.makedirs(f"{self.data_dir}/sessions/{sid}")
        return sid
    
    async def save_state(self, session_id, world_state):
        path = f"{self.data_dir}/sessions/{session_id}/world_v2.json"
        with open(path, "w") as f:
            json.dump(world_state, f, ensure_ascii=False, indent=2)
    
    # ... etc


class OrchestratorAdapter(PersistenceAdapter):
    """远程 orchestrator + PostgreSQL 存储"""
    def __init__(self, orchestrator_url: str, jwt_token: str):
        self.base_url = orchestrator_url
        self.token = jwt_token
    
    async def create_session(self, faction_id, scenario_id):
        resp = await httpx.post(f"{self.base_url}/games/histrategy/sessions", ...)
        return resp.json()["session_id"]
    
    # ... etc
```

## 前端统一方案

### 策略: 单体 HTML SPA，不引入框架

**原因**:
1. `histrategy --serve` 是自包含服务——用户不需要 npm install / node_modules
2. 前后端部署在一起，不需要独立的前端构建流程
3. 古代策略游戏，不需要 React/Vue 的组件化复杂度
4. 506 行的 HTML+CSS+JS 完全可以承载这个交互

**实现**:
- 重构 `histrategy/web/index.html` 为模块化 JS
- 所有 API 调用使用相对路径 (`/api/games/...`)
- CSS 统一为 dark Three Kingdoms 主题（现有风格已很好）
- `surprisal-portal` 通过 `<iframe>` 或直接 proxy 这个 HTML

### 前后端交互流程

```
用户打开页面
  ↓
GET / → web/index.html
  ↓
JS: fetch('/api/games', {method:'POST', body:{faction:'shu'}})
  ↓
Server: engine.set_player_faction('shu')
  ↓
返回 intro scene → JS 渲染

用户输入策令 → POST /api/games/{id}/command
  ↓
Server: engine.process_turn(decision)
  ↓
返回 narrative + state_changes → JS 渲染

用户点击 Plan → POST /api/games/{id}/plan
  ↓
Server: generate plan suggestions
  ↓
返回 advisor_court + suggestions → JS 渲染
```

## 实施路线

### Phase 1: Adapter 层 (1天)
1. 创建 `histrategy/server/persistence_adapter.py` — 定义 `PersistenceAdapter` ABC
2. 实现 `LocalFileAdapter` — 封装现有的 `_save_v2()` / `_rebuild_from_save()` 逻辑
3. 实现 `OrchestratorAdapter` — 封装现有的 `server/persistence.py` 逻辑
4. 在 `create_app()` 中根据 `ORCHESTRATOR_URL` 选择 adapter

### Phase 2: 前端重构 (2天)
1. 重构 `web/index.html` → 模块化 JS (`web/js/api.js`, `web/js/ui.js`, `web/js/game.js`)
2. 添加 CSS 变量系统 — 统一 dark 主题
3. 添加响应式布局 — 支持手机端
4. 添加 macro 引擎特有的 UI 元素（知识卡片、黑天鹅提示）

### Phase 3: Portal 集成 (1天)
1. `surprisal-portal` 中直接引用或 iframe 嵌入 histrategy 的 `index.html`
2. 确保 JWT token 正确传递（线上模式需要 auth，本地模式不需要）
3. 验证两端体验一致
