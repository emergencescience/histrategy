# 三國志略开源框架：自定义历史背景开发指南

> **日期**: 2026-06-08
> **适用版本**: SimPly v2 框架
> **目标读者**: 希望使用本框架开发其他时代（如春秋战国、罗马帝国等）的开发者和模组作者。

Histrategy (三國志略) 采用了 **SimPly v2 架构**（Physics Engine + LLM Narrative），并高度遵循 **Rules-as-Data**（规则即数据）的理念。
这意味着，将背景从"汉末三国"改为"春秋战国"或"哈利波特"，绝大多数情况下 **不需要修改一行 Python 代码**。

本指南将以**"春秋战国" (Warring States)** 为例，引导你如何基于开源框架开发自己的历史版本。

---

## 概述：SimPly v2 的解耦机制

整个引擎分为三层：
1. **Engine Layer (Python)**: 负责绝对的物理与数值推演（加减乘除、资源生产、伤亡计算）。**无需修改**。
2. **Knowledge Base (YAML/JSON)**: 世界初始状态、地图、人物、历史事件、系统参数。**重点修改区**。
3. **Narrative Layer (Prompt)**: 控制 LLM 的角色扮演与叙事风格。**重点修改区**。

---

## Step 1: 初始化世界数据 (World Data)

世界数据位于 `histrategy-knowledge/data/` 目录中。你需要创建新时代的对应数据文件。

### 1.1 地图与地域 (`territories.yaml`)
定义战国时代的诸侯国领土：

```yaml
# territories.yaml
territories:
  - id: t_qin
    name: 关中
    owner: f_qin
    stats:
      population: 3000000
      agriculture_level: 80
      commerce_level: 50
    borders: [t_chu, t_han, t_zhao, t_wei]
    special_trait: "易守难攻，水利发达（郑国渠）"
```

### 1.2 势力定义 (`factions.yaml`)
取代蜀、魏、吴，建立战国七雄：

```yaml
# factions.yaml
factions:
  - id: f_qin
    name: 秦
    ruler: c_ying_zheng
    capital: t_xianyang
    ideology: "法家"
    military_power: 500000
```

### 1.3 历史人物 (`characters.yaml`)
这是游戏里最为核心的数据。每个人物需要历史引用于标注，以增强代入感。

```yaml
# characters.yaml
characters:
  - id: c_bai_qi
    name: 白起
    alias: 武安君
    source: "史记·白起王翦列传"
    stats:
      leadership: 100
      might: 90
      intelligence: 85
      politics: 30
      charisma: 70
    personality:
      traits: [兵家, 冷酷, 战神]
      weakness: "不知政治进退，终遭坑杀"
```

---

## Step 2: 定制物理与社会规律 (Rules as Data)

不仅是初始数据，游戏内的**经济公式、科技树、兵种克制**也是可配置的。在 `histrategy-knowledge/rules/` 目录下进行修改。

### 2.1 兵种克制 (`military_rules.yaml`)

战国时代的特色是战车被步骑取代：

```yaml
# military_rules.yaml
units:
  chariot:
    name: "战车"
    attack: 50
    defense: 30
    mobility: 80
    cost: 500
    counters: [infantry]
    weak_against: [cavalry] # 胡服骑射后，骑兵克制战车
```

### 2.2 社会制度与合法性 (`governance_rules.yaml`)

三国拼的是"汉室正统"，战国拼的是"变法程度"。

```yaml
# governance_rules.yaml
legitimacy:
  base_concept: "变法图强"
  factors:
    - name: "商鞅变法执行度"
      weight: 0.6
      effect: "agricultural_output_multiplier"
    - name: "宗室怨言"
      weight: -0.4
      effect: "rebellion_chance"
```

---

## Step 3: 配置 LLM 叙事风格 (Prompt Templates)

要让游戏"闻起来"像战国，必须修改传递给大语言模型（如 Gemini / DeepSeek）的 System Prompts。
修改 `histrategy/llm/prompts/` 目录下的模板。

### 3.1 史官风格定义 (`system_narrator.prompt`)

**原版（三国志）**：
> "你是一位精通《三国志》的史官。请用半文半白的语言，以陈寿的笔触记录玩家的决策..."

**修改版（春秋战国）**：
> "你是一位精通《史记》与《战国策》的史官。请以司马迁的笔触，使用战国纵横家的口吻记录玩家的决策。注重描写诸侯之间的权谋、变法、合纵连横与游士的游说之辞。"

### 3.2 终局总结模板 (`endgame_summary.prompt`)
当玩家失败或统一天下时，指导 LLM 写出《太史公曰》的评语：
> "评价玩家这一局游戏，以『太史公曰：』开头。评价其是用法家之严、儒家之仁、还是兵家之诡..."

---

## Step 4: 定义历史引力事件 (History Engine)

Historical Gravity（历史引力）是引擎的灵魂，它决定了游戏不会沦为毫无约束的架空奇幻。
修改 `histrategy-knowledge/data/events.yaml`：

```yaml
# events.yaml
events:
  - id: changping_battle
    year: 260 BC
    gravity: 0.95   # 极高，结构性矛盾，秦赵必有一战
    trigger_conditions:
      - "qin_expansion_eastward == true"
    description: "长平之战爆发。秦赵两国在长平对峙，倾国之兵相遇。"
    structural_reason: "秦国东出与赵国保卫三晋的根本地缘冲突，不可调和。"

  - id: jingke_assassination
    year: 227 BC
    gravity: 0.30   # 较低，偶然事件，玩家可规避
    trigger_conditions:
      - "yan_under_threat == true"
    description: "荆轲刺秦王"
    structural_reason: "燕国太子丹的个人冒险行径。"
```
（注：引擎会根据玩家的动作动态改变这些事件的触发概率。Gravity 越高，玩家偏离此事件需要付出的代价和努力就越大。）

---

## Step 5: 测试与社区分享

### 5.1 本地测试
将你的新知识库挂载到引擎上运行：

```bash
# 启动游戏，指定自定义的战国知识库路径
histrategy --knowledge-dir ./histrategy-knowledge-warringstates/
```

### 5.2 提交到开源社区
由于你的工作全部在于 YAML 和 Prompt 的修改（零 Python 代码修改），你可以轻松地将这个剧本作为一个 **Plugin Repo** 发布到 GitHub：
- 推荐命名：`histrategy-plugin-warringstates`
- 其他玩家只需下载该文件夹，使用 `--knowledge-dir` 加载即可无缝畅玩你的"战国志"。

通过这种模式，无论是罗马帝国的《高卢战记》、西方奇幻的《冰与火之歌》、还是现代战争的剧本，都能够基于同一个底层的严谨物理引擎进行演绎！
