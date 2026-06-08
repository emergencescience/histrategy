# 三國志略 v2 引擎与 UI 颗粒级开发任务书

> **日期**: 2026-06-08
> **目标**: 为轻量级/快速型 LLM（如 Gemini 3.5 Flash）设计的离散化、明确上下文的开发任务拆解。

**AI Agent 执行指南**：
请按顺序认领以下 Task，每完成一个 Task 请提交一次 Commit 并运行单元测试验证。**每个任务的代码修改行数应控制在 50~150 行以内，避免幻觉。**

---

## 阶段 1: 核心物理引擎 (Phase 1 Engine)

### Task 1.1: 经济/农业公式计算 (Domestic Engine)
- **目标文件**: `histrategy-engine/src/histrategy_engine/domestic/grain.py`
- **任务描述**: 
  1. 实现 `calculate_grain_yield()` 函数。
  2. 逻辑：`粮食产量 = 基础种植面积 * 农业科技系数 * 季节修正因子`。
  3. 参数 `季节修正因子`：秋季为 1.5，春季为 0.5，冬夏为 1.0。
- **验证**: 编写 `tests/test_domestic_grain.py` 断言在秋季产量最高。

### Task 1.2: 合法性与民心系统 (Legitimacy Engine)
- **目标文件**: `histrategy-engine/src/histrategy_engine/governance/legitimacy.py`
- **任务描述**:
  1. 创建 `LegitimacyState` 数据类，包含 `current_score` (0-100)。
  2. 实现 `update_legitimacy(events_list)`。
  3. 如果 `events_list` 包含 `win_battle`，合法性 +5；包含 `heavy_tax`，合法性 -10。
- **验证**: 编写测试文件验证合法性分数的增减逻辑，边界值不得超过 0-100 范围。

### Task 1.3: 角色面板与忠诚度计算 (Character Engine)
- **目标文件**: `histrategy-engine/src/histrategy_engine/characters/loyalty.py`
- **任务描述**:
  1. 根据角色的 `politics`（政治）属性和玩家势力的 `legitimacy`（合法性）计算年度忠诚度衰减/增加。
  2. 公式：`delta_loyalty = (legitimacy - 50) / 10 + (politics > 80 ? -2 : 0)` (高政治人物忠诚度更容易因合法性低而下降)。
- **验证**: 实例化一个高政治人物测试合法性极低时的叛变概率。

---

## 阶段 2: 叙事反馈机制 (Phase 2 Narrative)

### Task 2.1: 终局史官列传生成器 (Endgame Summary)
- **目标文件**: `histrategy/llm/endgame_summary.py`
- **任务描述**:
  1. 引入 `histrategy.llm.adapter`。
  2. 构造 System Prompt："你是一位精通历史的史官，请以陈寿《三国志》的评语风格，为玩家写一篇总结传记。"
  3. 暴露函数 `generate_chronicle(player_events: list) -> str`，接收玩家游戏行为数组，组装 Prompt 请求大模型并返回。
- **验证**: 伪造一段包含"黄巾起义"、"统一中原"的事件数组，断言输出不为空且格式符合要求。

---

## 阶段 3: Web API 与录制管线 (Phase 3 Web & Video)

### Task 3.1: FastAPI 基础路由搭建
- **目标文件**: `histrategy/server/api.py`
- **任务描述**:
  1. 导入 `fastapi`，初始化 `app = FastAPI()`。
  2. 建立端点 `POST /api/games` 返回 `{ "game_id": "uuid-xxx" }`。
  3. 建立端点 `GET /api/games/{game_id}` 返回 dummy 的 `{"status": "running"}`。
- **验证**: `uvicorn histrategy.server.api:app --test`，使用 HTTP Client 测试响应是否 200 OK。

### Task 3.2: 史官列传 API 端点
- **目标文件**: `histrategy/server/api.py`
- **任务描述**:
  1. 新增端点 `POST /api/games/{id}/summary`。
  2. 读取本地存档 `~/.histrategy/sessions/{id}/world.json` 中的 `event_history`。
  3. 调用 Task 2.1 中的 `generate_chronicle()` 并作为 JSON 响应返回。
- **验证**: 构建 mock 存档数据，测试端点。

### Task 3.3: 一键视频生成任务队列包装
- **目标文件**: `histrategy/cli/record.py`
- **任务描述**:
  1. 实现一个简单的 `subprocess.run` 调用脚本。
  2. 读取 `frames/` 目录中的连续 PNG 图片（假设这些图片已由另一脚本生成）。
  3. 构造 `ffmpeg` 命令：`ffmpeg -framerate 0.5 -i frames/%04d.png -c:v libx264 -r 30 out.mp4`
  4. 函数 `generate_video(session_id) -> str` 返回生成的 `mp4` 文件绝对路径。
- **验证**: 在本地存入 3 张测试图片，验证是否能输出一个 `.mp4` 文件。

---

> **给后续 Agent 的提示**：
> 请不要试图一次性写完所有文件！先完成 Task 1.1，提交代码，确认测试通过后，再申请进入 Task 1.2。小步快跑，确保 `histrategy-engine` 的纯 Python 无状态测试 100% 覆盖。
