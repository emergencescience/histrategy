# 多场景同仓库架构设计

> **更新**: 2026-06-15 — 新增《凯撒余烬 Ashes of Caesar》场景，场景矩阵扩充至 3 个。

## 概述

histrategy 仓库同时托管多个策略游戏场景。引擎核心（GameRoom、WorldState、LLM Adapter、DB、Policy Engine）保持场景无关；各场景通过独立的 knowledge、prompts、rules 和 UI 包注入差异。

## 目标场景

| 场景 ID | 名称 | 时代 | 起始年 | 状态 |
|---------|------|------|--------|------|
| `three-kingdoms` | 《三國志略》 | 东汉末年至三国 | 207 | **生产** |
| `caesar` | 《凯撒余烬 Ashes of Caesar》 | 罗马共和国末期 | 44 BC | **骨架** |
| `shanhe-dingge` | 《山河鼎革》 | 明末清初 | 1644 | **骨架** |

## 目录结构

```
histrategy/
├── histrategy-engine/          # 场景无关的引擎核心
│   └── src/histrategy_engine/
│       ├── core/               # GameRoom, FactionSlot, WorldState
│       ├── db/                 # DB models, connection, migrations
│       ├── llm/                # adapter, game_master, npc_decision
│       ├── policy/             # policy_types, parser, validator
│       ├── parser/             # intent parser
│       └── server/             # REST API (FastAPI)
│
├── scenarios/                  # ★ 场景包（新增）
│   ├── three-kingdoms/
│   │   ├── scenario.toml       # 场景元数据
│   │   ├── knowledge/         # characters, factions, regions, events
│   │   ├── prompts/           # LLM prompt templates
│   │   ├── rules/             # YAML policy rules
│   │   ├── web/               # UI assets (SVG map, CSS, JS)
│   │   └── cli/               # CLI branding/entry
│   │
│   └── shanhe-dingge/
│       ├── scenario.toml
│       ├── knowledge/
│       ├── prompts/
│       ├── rules/
│       ├── web/
│       └── cli/
│
│   └── caesar/                  # ★ 新增：罗马内战
│       ├── scenario.toml
│       ├── knowledge/
│       ├── prompts/
│       ├── rules/
│       ├── web/
│       └── cli/
│
├── histrategy-sdk/             # Client SDK（场景无关）
├── histrategy-agent/           # 飞书/OpenClaw 适配（场景无关）
└── histrategy/                 # 历史代码 → 逐步迁移到 engine + scenarios
```

## 场景包规范

### `scenario.toml` 格式

```toml
[meta]
id = "three-kingdoms"
name = "三國志略"
name_en = "Histrategy"
era = "东汉末年至三国时期"
start_year = 207
start_season = "冬"
end_year = 280
description = "群雄割据的三国乱世，扮演一方诸侯逐鹿天下"

[engine]
version = "v3"                    # v1|v2|v3
quarter_per_year = 4
turn_timeout_human = 300          # 秒
turn_timeout_ai = 120

[factions]
# 可扮演势力列表
available = ["cao", "shu", "wu"]
# 完整势力定义从 knowledge/factions.json 加载

[territories]
# 地域定义从 knowledge/regions.json 加载
# 起始控制从 knowledge/initial_state.json 加载

[display]
icon = "🏯"
color_scheme = "three-kingdoms"
map_svg = "web/map.svg"
```

### 场景加载流程

```
CLI: histrategy --scenario three-kingdoms
  │
  ▼
ScenarioLoader(scenario_id)
  │
  ├─ 读取 scenarios/{id}/scenario.toml
  ├─ 加载 knowledge/factions.json   → WorldState.factions
  ├─ 加载 knowledge/regions.json    → WorldState.territories
  ├─ 加载 knowledge/characters.json → roster
  ├─ 加载 prompts/*.md              → LLM prompt templates
  ├─ 加载 rules/*.yaml              → PolicyEngine rules
  └─ 加载 web/*                     → UI assets
```

## 共享引擎核心（场景无关）

以下组件在所有场景间完全共享：

| 组件 | 路径 | 说明 |
|------|------|------|
| GameRoom | `engine/core/game_room.py` | 房间状态机，所有场景通用 |
| FactionSlot | `engine/core/faction_slot.py` | 势力槽位，场景通过 faction_id 区分 |
| WorldState | `engine/core/world_state.py` | 世界状态，`from_dict/to_dict` 序列化 |
| DB Schema | `db/schema.sql` | game_room.scenario 字段区分场景 |
| LLMAdapter | `llm/adapter.py` | LLM 调用，system prompt 来自场景 |
| PolicyEngine | `policy/` | 政策评估，规则来自场景 rules/ |
| REST API | `server/api.py` | API 路由，场景作为参数 |
| RoomManager | `server/room_manager.py` | 房间管理，场景无关 |

## 场景差异注入点

| 差异维度 | three-kingdoms | caesar | shanhe-dingge | 注入方式 |
|----------|----------------|--------|---------------|----------|
| 势力定义 | 曹操/刘备/孙权/袁绍/刘表... | 屋大维/安东尼/布鲁图斯/克利奥帕特拉/塞克斯图斯... | TBD | knowledge/factions.json |
| 地域地图 | 东汉十三州 + 城池 | 罗马行省 + 地中海岛屿 | TBD | knowledge/regions.json |
| 角色 | 20+ 历史武将 | 15 历史人物（含 traits） | TBD | knowledge/characters.json |
| 历史事件 | 讨董→官渡→赤壁→三国 | 恺撒遇刺→腓立比→亚克兴→帝国 | TBD | knowledge/events.json |
| 剧情弧线 | 8 个 arc_goals | 8 个 arc_goals（含海战弧线） | TBD | knowledge/arc_goals.json |
| System Prompt | 三国演义文白体 | 罗马史诗叙事 | TBD | prompts/system.md |
| 政策规则 | 屯田/科举/盐铁等 | 海战/宣传战/元老院政治 | TBD | rules/*.yaml |
| UI 地图 | 东汉 SVG 地图 | 罗马地中海 SVG 地图 | TBD | web/map.svg |
| CLI 品牌 | 三國志略 TUI | 凯撒余烬 TUI | TBD | cli/app.py |
| 特殊字段 | — | legions, ships, government | — | scenario.toml + schema.json |

## 迁移计划

### Phase 1: 建立框架（H16c ✅）

1. ✅ 创建 `scenarios/` 顶层目录
2. ✅ 创建 `scenarios/three-kingdoms/scenario.toml` + knowledge
3. ✅ 创建 `scenarios/shanhe-dingge/` 骨架
4. ✅ 实现 `ScenarioLoader` 类
5. ✅ 更新 `GameRoom` 使用 `ScenarioLoader`

### Phase 2: 场景充实（进行中）

1. ✅ 创建 `scenarios/caesar/` 罗马内战场景（scenario.toml + 10 knowledge JSON）
2. 充实 `caesar/prompts/` LLM system prompt
3. 充实 `caesar/rules/` 海战/宣传战 YAML
4. 充实 `shanhe-dingge/` knowledge 数据

### Phase 3: 引擎解耦（后续）

1. 将 `histrategy/` 下场景无关代码提取到 `histrategy-engine/`
2. 清理 `histrategy/` 目录，仅保留场景包
3. 实现 `histrategy --scenario <id>` CLI 路由

### Phase 4: 前端多场景 + 引擎增强

1. `/mp` UI 场景选择器
2. 引擎核心添加 naval framework
3. 引擎核心添加 political_influence dimension
4. BC 年份渲染支持

## 向后兼容

- `GameRoom.scenario = "207"` 继续有效，映射到 `three-kingdoms` 场景
- 现有 API 路径不变：`POST /api/games` → 默认创建 three-kingdoms 场景
- 环境变量 `HISTRATEGY_SCENARIO=three-kingdoms` 设置默认场景
- DB 中 `game_room.scenario` 字段无需变更

## 目录对比：Before vs After

```                                              
BEFORE:                              AFTER:
histrategy/knowledge/data/           scenarios/three-kingdoms/knowledge/
  factions.json                        factions.json
  characters.json                      characters.json
  regions.json                         regions.json
  events.json                          events.json
  arc_goals.json                       arc_goals.json
histrategy-knowledge/                scenarios/three-kingdoms/knowledge/
  characters/207_roster.json            roster.json
  geography/territories.json            territories.json
  timeline/207-223.json                 timeline.json
  scenarios/207_liubei.json             initial_state.json
                                      scenarios/three-kingdoms/
                                        scenario.toml          ★ NEW
                                        prompts/               ★ NEW
                                        rules/                 ★ NEW
                                      scenarios/shanhe-dingge/  ★ NEW
                                        scenario.toml
                                        knowledge/
                                        prompts/
                                        rules/
                                      scenarios/caesar/         ★ NEW
                                        scenario.toml
                                        knowledge/
                                          factions.json     (8罗马势力)
                                          characters.json   (15历史人物)
                                          events.json       (18历史事件)
                                          initial_state.json(44BC起点)
                                          timeline.json     (26时间线)
                                          arc_goals.json    (8剧情弧线)
                                        prompts/
                                        rules/
```
