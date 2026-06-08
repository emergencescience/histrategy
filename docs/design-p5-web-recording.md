# 三國志略 P5 — Web 客户端 + 录制管线 + 终局总结

> **日期**: 2026-06-08
> **状态**: 设计中
> **分支**: `feat/p5-web-recording`
> **依赖**: P1-P4 全部完成 ✓

---

## 1. 架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│                      用户接触面                                   │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────┐ │
│  │  CLI (现有)   │  │  Web 客户端   │  │  录制管线 (headless)    │ │
│  │  Rich TUI     │  │  HTML/SVG     │  │  → PNG 帧 → ffmpeg    │ │
│  └──────┬───────┘  └──────┬───────┘  └───────────┬─────────────┘ │
│         │                 │                      │               │
│         └─────────────────┼──────────────────────┘               │
│                           │                                       │
│                    ┌──────▼──────┐                                │
│                    │  REST API   │                                │
│                    │  (FastAPI)  │                                │
│                    └──────┬──────┘                                │
│                           │                                       │
│                    ┌──────▼──────┐                                │
│                    │  GameEngine │  ← 现有，不改                   │
│                    │  (v2 mode)  │                                │
│                    └─────────────┘                                │
└──────────────────────────────────────────────────────────────────┘
```

**核心原则**：GameEngine 零改动。API 是薄包装层。Web 客户端是纯前端。录制管线是独立脚本。

---

## 2. REST API (FastAPI)

### 2.1 端点设计

```
POST /api/games                → 创建新游戏 → {game_id, intro_scene}
GET  /api/games/{id}           → 游戏状态 → {world_state, turn_info}
POST /api/games/{id}/plan      → 获取 Plan Mode → {court_dialogue, suggestions}
POST /api/games/{id}/command   → 提交决策 → {narrative, state_changes, ...}
WS   /api/games/{id}/live      → WebSocket 实时推送 (P2 增强)
POST /api/games/{id}/save      → 持久化存档
POST /api/games/{id}/load      → 加载存档
POST /api/games/{id}/summary   → [新增] 获取终局总结 (史官列传)
POST /api/games/{id}/export_video → [新增] 触发一键视频生成任务
```

### 2.2 数据流

```
Browser                         FastAPI                       GameEngine
  │                                │                              │
  │── POST /games {faction:"shu"}──▶                              │
  │                                │── new GameEngine(faction)───▶│
  │                                │    set_player_faction()      │
  │                                │    get_intro_scene()         │
  │◀──── {game_id, intro} ────────│                              │
  │                                │                              │
  │── POST /games/{id}/plan ──────▶                              │
  │                                │── get_plan_data() ──────────▶│
  │◀──── {court_dialogue, ...} ───│                              │
  │                                │                              │
  │── POST /games/{id}/command ───▶                              │
  │   {decision: "发展农业"}        │                              │
  │                                │── process_turn("发展农业") ──▶│
  │◀──── {narrative, ...} ────────│                              │
```

### 2.3 实现策略

- **单文件**: `histrategy/server/api.py` (~250行)
- **依赖**: `fastapi`, `uvicorn`, `pydantic` (已在 `histrategy[web]` extras)
- **GameEngine 池**: 内存 dict `{game_id: GameEngine}`，进程内管理
- **存档**: 复用现有 `~/.histrategy/` 下的 `world_v2.json`
- **无需认证** (MVP): localhost only，公网部署时加 API Key

---

## 3. Web 客户端

### 3.1 技术选型

| 选项 | 决策 | 理由 |
|------|------|------|
| 框架 | **纯 HTML + vanilla JS** | 零构建、零依赖、零 npm |
| 地图 | **SVG (内嵌)** | 三國地图 30+ 城，SVG 最适合 |
| UI 框架 | **CSS (手写)** | Dark theme 汉风，200行CSS |
| 实时 | **HTTP polling** | MVP 不需要 WebSocket |
| 部署 | **单 HTML 文件** | 可以直接浏览器打开（API CORS 开） |

### 3.2 页面结构

```
┌──────────────────────────────────────────────────────────────────┐
│  [Header] 三國志略 · 建安12年·春   |   兵力 5,000   粮草 2,000      │
├─────────────────────┬────────────────────────────────────────────┤
│                     │                                            │
│    SVG 地图         │    📜 叙事面板                              │
│    (700×500)        │    "群臣趋前侍立...刘备端坐于新野府衙..."     │
│                     │                                            │
│    · 城池点         │    🎯 建议                                  │
│    · 势力色         │    1. 三顾茅庐 — 拜访卧龙岗                  │
│    · 行军线         │    2. 劝课农桑 — 发展新野农业                │
│    · 点击城池交互    │    3. 练兵备战 — 招募乡勇                    │
│                     │                                            │
│                     ├────────────────────────────────────────────┤
│                     │                                            │
│                     │    ⌨️ 决策输入框                            │
│                     │    > 准备去卧龙岗拜访诸葛亮                   │
│                     │    [执行] [跳过]                            │
│                     │                                            │
├─────────────────────┴────────────────────────────────────────────┤
│  [Footer] 三國志略 v2 · Emergence Science · 207 三顾茅庐剧本       │
└──────────────────────────────────────────────────────────────────┘
```

---

## 4. 终局总结与一键视频生成

游戏结束时，玩家需要获得强烈的成就感或历史反思，这是促进"分享"行为的核心。

### 4.1 史官列传 (AI Summary)

当触发 `Game Over`（统一天下、势力覆灭或玩家主动辞世）时，请求 `/api/games/{id}/summary`：

- **输入**：`event_history.json`（大事件时间线） + `player_memory.json`（玩家关键决策）
- **Prompt 设计**：要求 LLM 扮演《三国志》作者陈寿，用**传记体**写出这局游戏的历史评价。
- **输出格式**：
  - **总评（评曰）**："XX（玩家名），起于微末... 然穷兵黩武，终致倾覆。"
  - **历史偏离度点评**："若非赤壁之战提早发动，天下大势或未可知。"
  - **关键锚点回顾**：列出决定命运的 3 次操作。

### 4.2 一键视频生成 (One-Click Video)

在 Web 端结束页面提供**"生成我的历史演义 (Generate Video)"** 按钮，点击后：
1. Web 调用 `/api/games/{id}/export_video`
2. Server 启动后台 Celery 或 asyncio 异步任务。
3. 任务拉起 `histrategy/cli/record.py` (headless)，读取该局历史并快速重演。
4. 重演期间生成带有特定样式的 HTML 帧并截图。
5. 使用 `ffmpeg` 将图片帧合成 MP4 视频，附带 BGM。
6. 返回视频下载链接或分享链接。

---

## 5. 录制管线 (Headless Pipeline)

### 5.1 方案 C: Headless → 帧 → 视频

```
                    ┌─────────────────────┐
                    │  playthrough.py     │
                    │  (headless CLI)     │
                    │                     │
                    │  根据历史录像重演：    │
                    │  1. 恢复对应回合状态    │
                    │  2. 渲染 HTML 帧     │
                    │  3. 截图 (Playwright)│
                    │  4. 写入帧目录       │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  frames/            │
                    │  ├── 0001.png       │
                    │  ├── 0002.png       │
                    │  └── ...            │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  ffmpeg             │
                    │  -framerate 0.5     │  ← 每帧停留2秒
                    │  + 背景音乐/语音      │
                    │  → replay.mp4        │
                    └─────────────────────┘
```

### 5.2 帧渲染与视频风格

每帧用特定的 HTML 模板（与游戏操作 UI 不同，专门为视频优化）：
- **全屏深色背景**（#1a1a2e → 汉风暗红点缀）
- **中央焦点**：SVG 动态演变地图（领土变色清晰可见）
- **左侧边栏**：重大事件浮动字幕（如同电影旁白）
- **右下角**：年份与兵力数字快速跳动
- **0.5 fps**（每回合2秒）+ 关键事件额外停留1秒
- **BGM**：古琴/编钟 instrumental，在视频高潮（统一或败亡）自动加重音量。

---

## 6. 任务拆解

### H07g: P5 设计文档更新
- **输出**: 本文档 `/docs/design-p5-web-recording.md` 更新完毕。

### H07h: REST API 服务器
- **新建**: `histrategy/server/__init__.py`, `histrategy/server/api.py`
- **依赖**: `fastapi`, `uvicorn` — 加入 `pyproject.toml` extras
- **端点**: 包含完整的 `/summary` 和 `/export_video`。
- **工时**: 2.5h

### H07i: Web 客户端
- **新建**: `histrategy/web/index.html` (单文件)
- **内容**: 游戏主界面 + 终局史官列传界面 + 视频下载页
- **工时**: 3h

### H07j: 总结与录制管线
- **新建**: `histrategy/llm/endgame_summary.py` — 生成陈寿体传记
- **新建**: `histrategy/cli/record.py` — headless 视频回放引擎
- **依赖**: `playwright`, `ffmpeg-python`
- **工时**: 3h

### H07k: E2E 验证 + 视频产出
- **测试**: 完整模拟一局历史 → 生成史官列传 → 下载分享版 MP4。
- **工时**: 1h

---

## 7. 技术决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| Web 框架 | FastAPI | 轻量，与 Python 生态无缝 |
| 前端框架 | 无框架 | MVP 不需要 React/Vue，减少学习成本 |
| 地图方案 | 内嵌 SVG | 无需外部资源，离线可用，渲染视频帧极快 |
| 录制截图 | Playwright | headless 稳定，可完美控制网页渲染后截图 |
| 视频合成 | ffmpeg | 标准方案，可通过 python 子进程轻松调用 |
| 视频异步 | Asyncio Tasks | 简单游戏内建异步足矣，暂不需 Celery (可升级) |

---

*文档状态: 设计中 → 待执行*
