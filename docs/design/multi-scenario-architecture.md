# 多场景同仓库架构设计

> **更新**: 2026-06-15 — 新增《凯撒余烬 Ashes of Caesar》场景，NPC prompt 场景化+多语言支持。
> **状态**: Phase 1-2 ✅ / Phase 4 ✅ (Web UI) / Phase 3 ✅ (Prompt 架构) / Phase 5 ⚠️ (内容充实中)

## 概述

histrategy 仓库同时托管多个策略游戏场景。引擎核心（GameRoom、WorldState、LLM Adapter、DB、Policy Engine）保持场景无关；各场景通过独立的 knowledge、prompts、rules 和 UI 包注入差异。

> **[审阅评语 — 已处理]** ScenarioLoader 已以类的形式实现 (`histrategy/engine/scenario_loader.py`, 548行)。`load_territories()` 不再硬编码三国数据，从 `scenarios/{id}/knowledge/territories.json` 读取。新场景数据路径 `scenarios/caesar-44bc/knowledge/` 正确加载。

## 目标场景

| 场景 ID | 名称 | 时代 | 起始年 | 状态 | 势力数 | Web UI |
|---------|------|------|--------|------|--------|--------|
| `three-kingdoms` | 《三國志略》 | 东汉末年至三国 | 207 | **生产** | 3 | `?scenario=three-kingdoms` |
| `caesar-44bc` | 《凯撒余烬》 | 44-30 BC | -44 | **可玩** | 4 | `?scenario=caesar-44bc` |
| `shanhe-dingge` | 《山河鼎革》 | 明末清初 | 1644 | **骨架** | 4 | `?scenario=shanhe-dingge` |

> Caesar 4 主势力：屋大维、安东尼、克利奥帕特拉（埃及）、元老院。NPC-only 势力（布鲁图斯、雷必达、塞克斯图斯·庞培、帕提亚）不创建 AI slot，仅在 WorldState 中作为中立/背景势力存在。

## 目录结构

```
histrategy/
├── histrategy-engine/          # 场景无关的引擎核心
│   └── src/histrategy_engine/
│       ├── world/              # GameRoom, FactionState, WorldState
│       ├── domestic/           # 经济/粮食/税收
│       ├── military/           # 军事/兵种
│       ├── character/          # 武将/忠诚度
│       ├── governance/         # 合法性/政治影响力  ← 新增
│       ├── ai/                 # NPC AI
│       ├── turn/               # 回合控制器
│       └── rules/              # YAML 规则解释器
│
├── scenarios/                  # ★ 场景包（纯数据，无 Python 代码）
│   ├── three-kingdoms/
│   │   ├── scenario.toml       # 场景元数据
│   │   ├── knowledge/          # characters, factions, regions, events
│   │   ├── prompts/            # LLM prompt templates
│   │   ├── rules/              # YAML policy rules
│   │   ├── web/                # UI assets (SVG map, CSS, JS)
│   │   └── cli/                # CLI branding/entry
│   │
│   ├── caesar-44bc/            # ★ 罗马内战（4 势力）
│   │   ├── scenario.toml
│   │   ├── knowledge/
│   │   │   ├── factions.json   ← 4 主势力 + 4 NPC
│   │   │   ├── characters.json
│   │   │   ├── events.json
│   │   │   ├── initial_state.json
│   │   │   ├── territories.json
│   │   │   └── arc_goals.json
│   │   ├── prompts/
│   │   └── rules/
│   │
│   └── shanhe-dingge/
│       ├── scenario.toml
│       ├── knowledge/
│       ├── prompts/
│       └── rules/
│
├── histrategy-sdk/             # Client SDK（场景无关）
├── histrategy-agent/           # 飞书/OpenClaw 适配（场景无关）
└── histrategy/                 # 场景层 + CLI + Server
    ├── engine/
    │   ├── loader.py           # ScenarioLoader（函数式，待重构为类）
    │   └── game.py             # GameEngine（v1/v2/v3 路径，待精简）
    ├── server/api.py
    └── llm/
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

> **[审阅意见]** `scenario.toml` 格式合理，但缺少两个字段：
> - `[engine].year_direction = "positive" | "negative"`（支持 BC 年份倒数）
> - `[factions].npc_only = ["lepidus"]`（标记不可扮演的 NPC 势力）

### 场景加载流程（当前实现 ✅）

```
Web UI: /mp?scenario=caesar-44bc
  │
  ▼
GET /api/scenarios → ScenarioLoader.list_scenarios()
  ├─ 读取 scenarios/{id}/scenario.toml
  ├─ 加载 knowledge/factions.json → 过滤 npc_only: false
  └─ 返回 [id, name_cn, period, start_year, factions]

doCreateRoom → POST /api/rooms {scenario: "caesar-44bc", human_faction_ids: [...]}
  │
  ▼
room_manager.create_room(scenario="caesar-44bc")
  ├─ ScenarioLoader.load_factions() → 只取 npc_only: false (4势力)
  ├─ 人类指定势力 → OPEN/HUMAN slot
  ├─ 其余可扮演势力 → AI NPC slot
  ├─ ScenarioLoader.build_world_state() → 完整 WorldState (含NPC-only中立势力)
  ├─ room.major_npc_ids = set(npc_factions)  ← 场景特定
  └─ 同步 room.year / room.season (-44 / spring)
```

## NPC Prompt 架构（场景感知 + 多语言）✅

### 设计原则

NPC 决策 prompt 与场景绑定——不同时代需要不同的世界观、术语和战略思维。Caesar 的 NPC 不应该看到三国术语（"诸侯""屯田""民心"），正如三国 NPC 不应该看到罗马术语（"legions""元老院""公敌宣告"）。

### 加载优先级

```
NPCDecisionEngine._load_npc_prompt(scenario, language)
  │
  ├─ 1. scenarios/{scenario}/prompts/npc_decision_{language}.md
  │     例: caesar-44bc/prompts/npc_decision_zh-CN.md
  │         caesar-44bc/prompts/npc_decision_en.md
  │
  ├─ 2. scenarios/{scenario}/prompts/npc_decision_en.md  (English fallback)
  │
  ├─ 3. scenarios/{scenario}/prompts/npc_decision.md  (unversioned)
  │
  └─ 4. histrategy/llm/prompts/npc_decision.md  (三国默认，向后兼容)
```

### 缓存策略

模块级 `_NPC_PROMPT_CACHE: dict[tuple[scenario, language], str]` 缓存每个场景×语言组合的 prompt 内容，避免每次 NPC LLM 调用都读取文件。

### 渲染参数

场景感知的 NPCDecisionEngine 在 `_build_context()` 中额外输出：
- 势力个性参数（aggression, caution, diplomacy, mercy）← 从 FactionState 读取
- 周边势力估算兵力（FOW）← 启发式探报
- 近期历史摘要（最近 N 回合）← 从 TurnMemory 读取

### 调用链

```
DecisionBus.collect_all_decisions(room, ws, llm)
  │
  ├─ major_ai_slots() → room.major_npc_ids (场景特定)
  │
  └─ _collect_ai_decisions_parallel()
       └─ NPCDecisionEngine(llm, scenario=room.scenario)
            └─ generate() → _generate_llm()
                 ├─ _load_npc_prompt(scenario, language) → system prompt
                 ├─ _build_context() → 用户消息
                 └─ llm.chat_structured(messages, metadata={system_prompt_type: "npc_decision", ...})
```

### LLM 日志改进

- `metadata` 中显式传递 `system_prompt_type: "npc_decision"` → LLMAdapter 不再 fallback 到 `"custom"`
- 移除 NPCDecisionEngine 内的重复 `log_llm_call()` — LLMAdapter 已有日志记录
- `room_id` 和 `quarter_number` 通过 metadata 传递，确保日志关联到具体房间和季度

## 共享引擎核心（场景无关）

以下组件在所有场景间完全共享：

| 组件 | 路径 | 说明 |
|------|------|------|
| WorldState | `engine/world/world_state.py` | 世界状态，`from_dict/to_dict` 序列化 |
| FactionState | `engine/world/faction_state.py` | 势力状态，场景通过 faction_id 区分 |
| TurnController | `engine/turn/` | 回合控制，所有场景通用 |
| DomesticEngine | `engine/domestic/` | 经济/粮草，参数化 |
| MilitaryEngine | `engine/military/` | 军事/兵种，支持 naval_power 扩展 |
| LLMAdapter | `histrategy/llm/adapter.py` | LLM 调用，system prompt 来自场景 |
| REST API | `histrategy/server/api.py` | API 路由，场景作为参数 |

## 场景差异注入点

| 差异维度 | three-kingdoms | caesar | shanhe-dingge | 注入方式 |
|----------|----------------|--------|---------------|----------|
| 势力定义 | 曹/刘/孙/刘表 | 屋大维/安东尼/塞克斯图斯/雷必达 | 南明/清/大顺/郑氏 | knowledge/factions.json |
| 地域地图 | 东汉十三州 + 城池 | 罗马行省 + 地中海 | 明清版图 | knowledge/territories.json |
| 角色 | 20+ 历史武将 | 15 历史人物 | TBD | knowledge/characters.json |
| 历史事件 | 讨董→赤壁→三国 | 恺撒遇刺→腓立比→亚克兴 | 甲申→江南→永历 | knowledge/events.json |
| System Prompt | 三国演义文白体 | 罗马史诗叙事 | 末世多族史诗 | prompts/system.md |
| NPC Prompt | 诸侯/屯田/民心 | 军团/元老院/公敌 | TBD | prompts/npc_decision_{lang}.md |
| 政策规则 | 屯田/科举/盐铁 | 海战/宣传战/元老院 | 火炮/多族/正统衰减 | rules/*.yaml |
| 特殊字段 | — | legions, ships, government | artillery, legitimacy_decay | schema.json + rules |

## 迁移计划（已更新）

### Phase 1: 引擎瘦身 ✅ 部分完成

1. ✅ Pre-Phase 去重: `_build_engine_stack()` 提取, `FACTION_CONFIGS` 删除, `load_territories()` 去硬编码
2. ⚠️ `state/world_state.py` → `histrategy_engine.world.WorldState`（向后兼容 shim 已加）
3. ⬜ `offline_sim_engine.py` + `resilient_sim_engine.py` 删除（需待 v1 退役）
4. ⬜ `game.py` 从 2,866 精简到 ~800 行（部分完成: ~2,400 行）

### Phase 2: ScenarioLoader 升级 ✅ 已完成

1. ✅ `loader.py` 重构为 `ScenarioLoader` 类 (548行)
2. ✅ `load_territories()` 从 `scenarios/{id}/knowledge/territories.json` 读取
3. ✅ `scenarios/caesar-44bc/` 完整知识库加载
4. ✅ `scenario.toml` 解析

### Phase 3: 场景内容充实 ⚠️ 进行中

1. ✅ 《凯撒余烬》prompts/system.md（双语，英文 ~3149 词 / 中文 ~2983 词）
2. ✅ 《凯撒余烬》prompts/npc_decision_en.md + npc_decision_zh-CN.md
3. ✅ 《凯撒余烬》rules/naval.yaml
4. ✅ 《凯撒余烬》factions.json — 精简为 4 主势力（移除 NPC-only）
5. ✅ 《凯撒余烬》initial_state.json — 起始年修正为 -44
6. ⬜ 《山河鼎革》knowledge 数据充实

### Phase 4: 前端多场景 + 持久化完善 ✅ 部分完成

1. ✅ `mp.html` 完全重写为场景感知（动态势力选择、BC年份渲染）
2. ✅ `/api/scenarios` REST 端点
3. ✅ 创建房间时动态加载 NPC 势力（不再硬编码三国）
4. ⬜ 引擎核心添加 `naval_power` framework
5. ⬜ 引擎核心添加 `political_influence` dimension
6. ⬜ `room_manager.py` 去内存缓存（SDK + SQLite 持久化）

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
histrategy-knowledge/                scenarios/three-kingdoms/knowledge/
  characters/207_roster.json            roster.json (unified)
  geography/territories.json            territories.json (not hardcoded)
  scenarios/207_liubei.json             initial_state.json

loader.py:                           ScenarioLoader(scenario_id):
  load_territories()  ← hardcoded      load_territories()  ← from scenarios/{id}/
  load_scenario("207")                 load_from_toml("scenario.toml")

scenarios/caesar/knowledge/          scenarios/caesar/knowledge/
  factions.json (8势力)   ← 错误        factions.json (4势力)   ← 修正
```
