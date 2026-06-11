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

## 阶段 4: Rules-as-Data 与 非对称 NPC AI (Phase 4)

### Task 4.1: 规则配置外置化与公式解释器 (Rules-as-Data)
- **目标文件**: `histrategy-engine/src/histrategy_engine/rules/interpreter.py` [NEW] 与 `histrategy-engine/src/histrategy_engine/domestic/grain.py`
- **任务描述**:
  1. 将硬编码的粮食消耗公式移到 YAML 规则配置文件（如 `rules/three-kingdoms/economy.yaml`）。
  2. 实现一个规则表达式解释器 `RuleInterpreter`，能够安全解析和执行来自 YAML 的字符串公式，例如将 `"troops_actual * 0.5 * season_factor + population * 0.02"` 绑定到当前的 Faction/Territory 变量并计算数值。
  3. 修改 `DomesticEngine` 使其调用 `RuleInterpreter` 完成粮食消耗的结算，确保旧公式的结果向前兼容。
- **验证**: 编写测试文件验证从 YAML 公式加载并计算出的粮食消耗值与原硬编码公式结果一致。

### Task 4.2: 非线性离散指令判定与覆写机制 (Non-Linear Sabotage)
- **目标文件**: `histrategy-engine/src/histrategy_engine/military/__init__.py` (或相关模块)
- **任务描述**:
  1. 在 `CommandValidator` 和 `TurnController` 中，实现对 `sabotage(target_general, type="assassinate"|"bribe")` 这种非线性/离散指令的解析与拦截。
  2. 规则逻辑：根据目标武将的性格（如 `caution`）和忠诚度（`loyalty`），计算判定刺杀/策反概率。
  3. 执行效果覆写：若判定成功，直接在势力中将目标武将移除（在野或死亡），并对原军队施加一个一次性的 `morale_penalty`（士气减半）覆写效果。
- **验证**: 在 `tests/test_military_sabotage.py` 中测试在武将低忠诚度时发起刺杀/策反指令，断言其太守/主帅职务被成功解除，军队士气被削减。

### Task 4.3: 局部世界视角投影器 (Fog-of-War LocalWorldState)
- **目标文件**: `histrategy-engine/src/histrategy_engine/ai/fog_of_war.py` [NEW]
- **任务描述**:
  1. 实现 `LocalWorldStateProjector` 类。
  2. 暴露接口 `project_local_state(global_ws: WorldState, faction_id: str) -> LocalWorldState`。
  3. 过滤逻辑：
     - 仅保留当前势力自身的所有数据（城池、资源、兵力）。
     - 对接壤的邻近领土，仅保留可见驻军规模；对非接壤的第三方势力，隐藏其实际兵力、粮草与资金数值（设置为模糊状态）。
     - 保留全局史官纪事 log（公开信息）。
- **验证**: 编写测试用例验证从全局状态投影出的 `LocalWorldState` 中不包含远端敌对势力的实际粮草与隐藏军队信息。

### Task 4.4: 双层 NPC AI 决策规划器 (Dual-Horizon NPC Planner)
- **目标文件**: `histrategy-engine/src/histrategy_engine/ai/__init__.py` (重构 `DecisionEngine`)
- **任务描述**:
  1. 重构 `DecisionEngine`，使其仅接受 `LocalWorldState`（局部非对称信息）作为决策输入。
  2. 整合双层决策：
     - **战术 Heuristic**：检查边界防守（`evaluate_threats`）与弱邻扩张（`evaluate_opportunities`），下达即时的征兵、驻防或偷袭命令。
     - **战略 LLM Planner**：调用 LLM，根据当前局部视野、历史公开战绩以及本势力君主的性格特征，输出长期战略意图建议，并把战略倾向转化为短期命令权重。
- **验证**: 编写集成测试，在一个具有战争迷雾（敌军兵力隐蔽）的场景中，NPC 能够基于可见信息做出进攻或退守决策，且不使用任何隐藏信息。

---

## 阶段 5: 大模型对齐与自我审查层 (Phase 5 LLM-Alignment)

### Task 5.1: 对齐 Prompt 与数据输入构造
- **目标文件**: `histrategy/llm/game_master.py` (或新建 `histrategy/llm/alignment.py`)
- **任务描述**:
  1. 实现 `construct_alignment_context(raw_result, random_factors, events)` 函数，将 Lanchester 计算结果、气候、事件注脚整合成大模型上下文。
  2. 设计 System Prompt 要求大模型仅微调数值（例如伤亡人数上下浮动最大 20%）并输出 JSON 格式。
- **验证**: 单元测试模拟投喂 raw_result，验证大模型返回的 JSON 是否具备规定格式。

### Task 5.2: 审查校验器 (Reflective Validator) 实现
- **目标文件**: `histrategy/llm/game_master.py` (或对齐校验模块)
- **任务描述**:
  1. 编写验证逻辑：当大模型输出的对齐数值（如兵力伤亡）超出原始数值仿真的限额区间（如 $\pm 25\%$）时，拦截并拦截并发起 re-prompt：“您修正的数值超出安全边界，请重新生成合理数据”。
  2. 限制最大自省迭代次数为 3 次，超时则强制截断并使用物理引擎基础数值。
- **验证**: Mock 一个大模型输出超标的响应，断言系统触发了重试或安全截断。

---

## 阶段 6: 局部世界视角投影与迷雾 (Phase 6 Fog-of-War)

### Task 6.1: 侦察与反侦察行动指令 (Reconnaissance Commands)
- **目标文件**: `histrategy-engine/src/histrategy_engine/military/__init__.py` 或 `TurnController`
- **任务描述**:
  1. 实现 `scout(target_region)` 命令逻辑：消耗 200 资金向目标邻近地区派侦察兵，在下回合的 `PerceivedWorldState` 中精确显示该地区曹军的实际驻军（波动率降低至 $\pm 5\%$）。
  2. 实现 `disinform(target_region, fake_troops)` 命令逻辑：制造虚假扎营痕迹误导对手，使对手看到的感知兵力被覆写为 `fake_troops`。
- **验证**: 编写测试用例，断言施加 `disinform` 后对方的观测值发生了偏离，施加 `scout` 后观测值回归精准。

## 阶段 7: AI 军师助手模块与 NPC 规划器统一 (Phase 7 Unified Strategic Advisor)

### Task 7.1: 统一军师/规划器分析接口
- **目标文件**: `histrategy/llm/advisor.py` [NEW]
- **任务描述**:
  1. 实现 `StrategicAdvisor` 类，支持 `evaluate_strategy(local_state, personality, query=None) -> dict` 方法。
  2. 人类玩家提问时，传入玩家的 `local_state` 与问题文本（`query`），大模型扮演诸葛亮/荀彧，分析局势、敌人弱点并返回锦囊妙计（自然语言文本）。
  3. NPC AI 决策时，传入 NPC 自身的 `local_state` 与性格特征，大模型扮演该 NPC 君主，返回局势大局观分析（自然语言文本）以及各地区进攻/防守的建议权重数据（结构化 JSON 数据），由 `DecisionEngine` 转换成军事/内政指令。
  4. 在 CLI/Web 端暴露交互界面以支持用户问询。
- **验证**: 编写测试验证输入：“我军现在进攻宛城胜算几何？”，断言军师给出的分析仅基于局部可见的 `local_state` 信息；验证在无 `query` 传入时，返回建议权重 JSON 数据。

---

> **给后续 Agent 的提示**：
> 请不要试图一次性写完所有文件！先从 Task 4.1 开始，一步步完成，并在每次提交前运行 pytest 以确保 `histrategy-engine` 的测试 100% 覆盖通过。
