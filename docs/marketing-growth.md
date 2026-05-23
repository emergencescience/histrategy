# Marketing & Growth Strategy: 三國志略 (Histrategy)

> **Status**: Draft v0.1
> **Owner**: Prometheus (Hermes Agent)
> **Strategic Review**: @Host-MY (2h/week)
> **Date**: 2026-05-23

---

## 0. 核心哲学

> **This project is marketing-driven, not tech-driven.**

技术是实现手段，市场增长是目的。每一个开发决策都必须回答："这如何帮助我们获得更多用户？"

三國志略首先是 **emergence.science 品牌的旗舰营销资产**，其次才是一个游戏。

---

## 1. 品牌架构

### 1.1 三层品牌价值

```
            ┌──────────────────────────────────────┐
            │      emergence.science (母品牌)        │
            │  "Agent Economy" × "AI Task Platform"  │
            └────────────────┬─────────────────────┘
                             │ 关联
                             ▼
            ┌──────────────────────────────────────┐
            │       三國志略 / Histrategy (子品牌)    │
            │    "AI-Native History Strategy Game"   │
            └────────────────┬─────────────────────┘
                             │ 产品形态
                             ▼
   ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
   │ GitHub 开源项目  │  │ Steam 商业版本  │  │ B站/YouTube    │
   │ (开发者/社区)    │  │ (策略玩家)      │  │ (内容/品牌)     │
   └────────────────┘  └────────────────┘  └────────────────┘
```

### 1.2 品牌信息层级

| 受众 | 核心信息 | 渠道 |
|------|---------|------|
| **开发者** | "The first open-source AI history strategy game. Python, CLI, MIT licensed." | GitHub, HN, Reddit |
| **策略玩家** | "用AI重写三国——你的每一道诏书都可能改变历史。" | Steam, B站, 知乎 |
| **AI 关注者** | "AI原生游戏的真正实践——不是ChatGPT套壳，是完整的AI+game loop。" | Product Hunt, X/Twitter |
| **Emergence 用户** | "我们的AI Agent平台也能帮你做游戏！" | emergence.science 站内 |

---

## 2. 用户旅程 (6-Month Funnel)

```
Month 1-2: 冷启动 (开发者社区)
   GitHub Star 100 → 1,000
   ├── 开源发布 (Show HN / Reddit r/Python)
   ├── Python pip install histrategy (零摩擦体验)
   ├── 开发者博客/教程 (Medium, Dev.to, 知乎)
   └── Discord 社区建立 (50-100 人)

Month 2-3: 破圈 (策略游戏玩家)
   Steam 愿望单 0 → 5,000
   ├── Web UI 发布 (降低非开发者门槛)
   ├── B站实况视频 (找中小UP主)
   ├── 三国策略论坛/贴吧推广
   └── Product Hunt 发布

Month 3-4: 增长飞轮 (内容病毒传播)
   GitHub Stars 1,000 → 5,000
   ├── AI生成"诏书"截图病毒传播
   ├── "用AI写诏书拯救汉室" 短视频系列
   ├── 玩家故事征集 (UGC 内容)
   └── Steam 新品节 / Next Fest

Month 4-6: 商业化 (收入启动)
   Steam Early Access 发布
   ├── 第一个付费 DLC (春秋 / 战国剧本)
   ├── KOL 集中推广 (1-3个大UP主)
   ├── 用户推荐计划
   └── emergence.science Credits 集成
```

---

## 3. 冷启动策略 (Phase 1-2, 优先级最高)

### 3.1 GitHub 开源发布 (D-0 核心)

**为什么 GitHub 是第一站？**
- 我们的游戏是 CLI 工具 → 天然适合开发者社区
- 开源降低信任门槛（vs 青干工作室的闭源+Token争议）
- GitHub Stars 是后续所有渠道的 Social Proof

**发布检查清单**：

| 项目 | 状态 | 负责人 |
|------|------|--------|
| README.md: 中英双语 | 📝 已有初版 | Prometheus |
| 安装: `pip install histrategy` | 📝 需要发布到 PyPI | Prometheus |
| Demo GIF / Asciinema 录屏 | 📝 需要录制 | Prometheus |
| Contributing Guide | 📝 需要写 | Prometheus |
| COC + License (MIT) | 📝 需要加 | Prometheus |
| 项目 logo (ASCII art) | 📝 已有一个 | Prometheus |

**发布渠道与文案**：

```
Show HN: "Histrategy – Open-source AI history strategy game in your terminal"
HN audience: 20K+ unique visitors, high developer conversion
Best time: 10AM ET on a weekday (Tuesday-Thursday)

Reddit r/Python: "I built an AI-powered Three Kingdoms strategy game for your terminal"
Reddit r/roguelikes: "Text-based history strategy game with AI NPCs"
Reddit r/interactivefiction: "Open-source AI-driven historical simulation"

知乎： "我用AI做了一个三国策略游戏，完全开源（技术拆解）"
知乎受众：30-50K 阅读，高质量开发者+三国爱好者
```

### 3.2 病毒传播设计 (Built-in Virality)

**核心素材 1: "AI 诏书" 截图**

这是最强病毒素材——玩家输入一句自然语言，AI生成文言风格的诏书，然后推演结果。

```
示例：
玩家输入："朕要联合孙权共抗曹操，谁能给我牵线？"

AI 生成诏书：
"诏曰：孤与吴侯孙氏，有唇齿之依。今曹贼势大，
若不合力，必为所图。遣辩士鲁肃为使，说以利害，
约共进退。钦此。"

AI 推演结果：
- 孙权：同意结盟（关系+15）
- 曹操：震怒，加强合肥防线
- 周瑜：建议孙权趁机取荆州
```

这种内容天然适合：
- **小红书/知乎** — "一键生成文言文" (中国用户爱文言写作)
- **Twitter/X** — "I wrote one sentence and AI generated this imperial edict"
- **B站短**视频 — "AI三国：我的诏书让曹操吓尿了"

**核心素材 2: "What If" 历史对比**

```
"如果曹操在官渡之战前选择……"
"如果刘备听了田丰的建议……"
"如果董卓不下令迁都……"
```

AI 生成 alternate history → 社交媒体讨论 + 用户分享自己的结局。

**核心素材 3: "97% 玩家活不过崇祯五年" 对标**

青干工作室的数据是"97% 玩家活不过崇祯五年"。我们做三国版本：
- "你在三国能活几年？"
- "评测你的治国能力——AI三国模拟器"
- 每个人分享自己的 "死法"（被曹操灭 / 被吕布斩 / 内政崩盘）

### 3.3 KOL 矩阵 (Phase 2-3)

| 层级 | UP主类型 | 粉丝量 | 数量 | 合作形式 | 预算 |
|------|---------|--------|------|---------|------|
| S级 | 三国区头部（稚嫩的魔法师、芒果冰等） | 100-500万 | 2-3 | 赞助视频+直播 | 中 (5-10K/个) |
| A级 | 历史策略UP主 | 20-100万 | 5-10 | 免费Key+推广费 | 低 (1-3K/个) |
| B级 | 技术/开源UP主 | 5-20万 | 10-20 | 共创内容 | 免费 |
| C级 | 直播实时 | — | 持续 | 直播掉落 Key | 免费 |

**B站特有优势**：B站的"三国内容"生态极其成熟。从历史考据到游戏攻略，三国是 B 站最大的内容品类之一。我们不需要教育市场，只需要提供新工具。

---

## 4. 内容引擎 (持续运营)

### 4.1 内容类型矩阵

| 类型 | 频率 | 目的 | 平台 |
|------|------|------|------|
| **"拯救汉室" 系列** | 每周1期 | 正片实况，展示游戏深度 | B站 |
| **AI诏书短视频** | 每周3-5条 | 病毒传播，展示AI能力 | B站短视频/小红书 |
| **技术博客** | 每2周1篇 | 开发者社区建设 | 知乎/Medium/HN |
| **更新日志** | 每次发布 | 社区维护 | GitHub/Discord |
| **玩家故事** | 每周1篇 | UGC 激励 | 知乎/B站专栏 |
| **What If 系列** | 每周1期 | 历史+AI跨界内容 | B站/知乎 |

### 4.2 AI 辅助内容生产

**工具链**：
```
[游戏引擎] → 自动生成叙事文本 → [AI 润色/扩写] → [发布草稿]
                                              ↓
                                      [@Host-MY 审阅发布]
```

Prometheus 负责：运行游戏生成素材 → AI 扩写成文章/帖子 → 保存草稿
@Host-MY 负责：审阅 → 发布（每周最多2小时）

---

## 5. 与 emergence.science 的深度绑定

这是最重要的战略点。三國志略不只是个游戏，它是 emergence.science 的 **Trojan Horse**。

### 5.1 绑定点

| 绑定点 | 形式 | 用户感知 |
|--------|------|---------|
| README 顶部 | "Powered by Emergence Science" | 品牌印象 |
| 游戏启动画面 | "Emergence Science presents..." | 每次启动曝光 |
| AI Credits | 可选使用 emergence.science Credits 池 | 引流到平台 |
| 游戏内 Skill | 在 emergence.science 上发布游戏引擎为 Skill | 平台案例 |
| 社区 | GitHub Issue/Discord 讨论 → emergence.science 站内讨论 | 用户迁移 |
| 内容 | 所有视频/文章标题后缀 "| Emergence Science" | 品牌关联 |

### 5.2 长期变现桥梁

```
                   三國志略 玩家
                      │
           ┌──────────┴──────────┐
           ▼                      ▼
    Steam 购买 DLC         emergence.science 注册
    (直接收入)               (平台用户增长)
                               │
                               ▼
                    发布/接 Bounty → 平台活跃
                               │
                               ▼
                    Credits 消费 → 平台收入
```

游戏是"漏斗顶部"——低门槛、高趣味的入口。玩家在游戏中接触 emergence.science 品牌后，自然流向平台。

### 5.3 一个具体例子

```
游戏内弹出："想用你自己的 API Key 玩？注册 emergence.science 获得免费 AI Credits"
点击 → 注册 → 获得 10 Credits → 可以玩 50 回合 AI 模式 → Credits 用完 → 
发现平台上还有内容生成 Bounty → 开始接单赚 Credits → 成为平台活跃用户
```

---

## 6. 竞品应对策略

### 6.1 针对青干工作室

| 我们的优势 | 青干的劣势 |
|-----------|-----------|
| 🟢 开源 (开发者信任) | 🔴 闭源 + Token 争议 |
| 🟢 三国 (全球IP) | 🔴 崇祯 (中国市场天花板) |
| 🟢 多势力多结局 | 🔴 单主角线性叙事 |
| 🟢 0 元起步 | 🔴 48 元门槛 |

**不直接攻击**（蹭热度反而帮他们卖游戏），而是：
- 定位差异化："我们做的是策略 + AI 的深度融合，不是冒险游戏+AI皮肤"
- 强调开源："你的数据你的模型你的游戏"
- 吸引他们对 Token 不满的用户

### 6.2 针对三国同行

如果青干转向三国，或者出现其他三国 AI 游戏：
- **速度优势**：我们已经在做了
- **社区优势**：开源社区一旦建立，很难被闭源竞品超越
- **定位优势**：我们是"开发者友好的 AI 策略引擎"，不是"又一个三国游戏"

---

## 7. 增长指标 (North Star)

### 7.1 Phase 1 (May 27 - Jun 7)

| 指标 | 目标 | 衡量方式 |
|------|------|---------|
| GitHub Stars | 100 | GitHub |
| `pip install` 下载 | 200 | PyPI |
| Discord 成员 | 30 | Discord |
| 游戏游玩 (开发者) | 50 unique | GitHub 讨论 + Issue |

### 7.2 Phase 2 (Jun 8 - Jul 15)

| 指标 | 目标 | 衡量方式 |
|------|------|---------|
| GitHub Stars | 1,000 | GitHub |
| Steam 愿望单 | 5,000 | Steamworks |
| B站视频播放 | 50万 | B站 |
| Discord 成员 | 500 | Discord |
| 月活跃玩家 | 100 | Google Analytics (Web) |

### 7.3 Phase 3 (Jul 16 - Aug 31)

| 指标 | 目标 | 衡量方式 |
|------|------|---------|
| GitHub Stars | 5,000 | GitHub |
| Steam 销量 | 1,000+ | Steamworks |
| B站视频播放 | 500万 | B站 |
| 月活跃玩家 | 1,000 | 游戏内统计 |
| 月收入 | $1,000+ | Steam + DLC |
| emergence.science 导流 | 100 注册/月 | 平台统计 |

---

## 8. 执行节奏 (Weekly)

### 每周 Prometheus 自动执行

| 天 | 任务 | 输出 |
|---|------|------|
| Mon | 开发冲刺 (devops) | 代码/功能/修复 |
| Tue | 内容生成 | 1篇技术文章/游戏素材 |
| Wed | 社区互动 | Reddit/HN/B站 回复 |
| Thu | 开发冲刺 | 代码/功能 |
| Fri | 内容生成 + 发布准备 | 周报 + 草稿 |
| Sat | Play test / Bug hunt | Issue 列表 |
| Sun | Planning + 市场扫描 | 下周计划 |

### @Host-MY 的 2 小时/周

| 任务 | 预估时间 | 输出 |
|------|---------|------|
| 审阅发布内容 (视频/博客) | 30-60 min | 确认/修改 → 发布 |
| 审阅游戏方向 | 20 min | 方向确认 |
| 高峰决策 | 20-30 min | 关键决策 |
| 社交媒体互动 (可选) | 10-20 min | 回复/转发 |

---

## 9. 急先锋行动 (Next 72 Hours)

### 立即执行 (不等待任何审批)

| # | 动作 | 理由 | 时间 |
|---|------|------|------|
| 1 | Git init + push 到 emergencescience/histrategy | 建立公开仓库 | 本文完成后 |
| 2 | 更新 README.md (中英双语 + 游戏截图) | 为开源发布做准备 | 同上 |
| 3 | LLM adapter 多 provider 改造 | 降低使用门槛 | 同上 |
| 4 | 录制 asciinema demo GIF | 核心营销素材 | 同上 |
| 5 | 准备 Show HN 投稿帖草稿 | 发布当天用 | 草稿完成 |
| 6 | 准备知乎第一篇文章草稿(技术拆解) | 发布当天用 | 草稿完成 |
| 7 | Discord 服务器建立 | 社区据点 | 草稿完成 |

> **发布日 (D-0)**: GitHub 公开 + Show HN + r/Python + 知乎同时发布 ≈ 1-2 天内获得初始 100 Stars
