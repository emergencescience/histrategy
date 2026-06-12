# 三国志略 (Histrategy) — MacBook 本地启动指南

## 前提条件

- macOS 13+ (Apple Silicon / Intel 均可)
- Python 3.10+
- DeepSeek API Key（推荐，也可用 OpenAI / 通义千问 / OpenRouter）

## 1. 克隆代码 + 安装

```bash
# 克隆仓库并切换到宏观引擎分支
git clone https://github.com/emergencescience/histrategy.git
cd histrategy
git checkout feat/macro-historical-engine

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install --upgrade pip
pip install -e .

# 验证安装
histrategy --help
```

## 2. 配置 API Key

```bash
# DeepSeek（推荐，性价比最高）
export DEEPSEEK_API_KEY='sk-your-key-here'

# 或者用 OpenRouter
export OPENROUTER_API_KEY='sk-or-v1-xxx'

# 可选：自定义 LLM 模型
export MACRO_POLICY_MODEL='deepseek-v4-pro'   # 策略仿真（默认 deepseek-v4-pro）
export MACRO_PARSER_MODEL='deepseek-v4-flash' # 指令解析（默认 deepseek-v4-flash）
```

## 3. 启动游戏

```bash
# === 宏观引擎模式（推荐） ===
export HISTRATEGY_MACRO=1
histrategy                    # Rich TUI 界面

# === 纯文本 Dev 模式（调试推荐） ===
histrategy --dev              # 纯文本输入输出
histrategy --dev --faction 2  # 直接选刘备
histrategy --dev --faction 3  # 直接选孙权
histrategy --new              # 强制新游戏（忽略存档）

# === 可选的 factions ===
# 1 = 曹操 (cao)
# 2 = 刘备 (shu)
# 3 = 孙权 (wu)
# 4 = 刘表 (liubiao)
```

## 4. 查看 LLM 调用日志

```bash
# 游戏日志所在目录
ls ~/.histrategy/rooms/<room-id>/logs/

# 实时监控 LLM 调用
tail -f ~/.histrategy/rooms/<room-id>/logs/llm_usage.log

# 查看仿真历史（每轮状态快照）
cat ~/.histrategy/rooms/<room-id>/logs/simulation_history.jsonl | jq .
```

## 5. 游戏操作说明

宏观引擎模式下，你扮演势力君主，**每季度发布一次政令**（自然语言）：

| 操作 | 说明 |
|------|------|
| 输入政令 | 输入自然语言策略指令，可跨多领域 |
| `plan` | 重回战略规划（AI 参谋团建议） |
| `state` | 查看当前势力状态 |
| `exit` | 保存退出 |

### 政令示例

```
【曹操 207年春】
1. 将税率从40%降至30%，推行屯田制增加粮食产出
2. 任命荀彧为尚书令主管内政
3. 派出使者携带重礼前往建业与孙权结好，孤立刘表
```

引擎会自动解析你的政令 → 季度经济计算 → LLM 生成叙事 + 领地变化 + 知识卡片。

## 6. 运行测试

```bash
pytest tests/ -v                      # 全部测试
pytest tests/test_macro_policy*.py -v  # 仅宏观引擎测试（206 passed）
```

---

**注意**: 当前分支为 `feat/macro-historical-engine`，尚未合并到 main 分支。前端 Web UI 暂不支持宏观模式——先用 CLI 验证体验，再决定前端适配方案。
