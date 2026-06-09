# Histrategy Roadmap
> 三國志略 — Open-Source Physics-Driven Historical Strategy Game
> Last updated: 2026-06-08

---

## Vision

An open-source, extensible historical strategy game engine where **deterministic physics meets LLM narrative**.

- **For players**: 在策略推演中理解历史的深层逻辑 — 不是选择题，不是 AI 胡说八道
- **For developers**: A pluggable rules-as-data framework to build any era's strategy game (Rome, Warring States, Harry Potter)
- **For researchers**: A documented experiment in layered LLM game design
- **For the community**: YAML-driven rules and knowledge base that anyone can contribute to — zero code required

**Differentiators**:
- vs 《崇祯模拟器》: Open-source, BYOK, deterministic engine prevents LLM hallucination
- vs 《三国志》: Natural language input, LLM narrative, community-extensible rules
- vs AI Dungeon: Deterministic physics engine guarantees fairness

---

## 1. Design Philosophy Evolution

### 1.1 Timeline

```
v0.1 (2026-05)  "LLM is the engine"
  └── LLM handles everything: narration + numbers + NPC + events
  └── Problem: LLM hallucination breaks fairness (粮食翻倍, 兵力凭空出现)
  └── Lesson: LLM as engine ≠ reliable engine

v0.2 (2026-05)  "LLM + Offline Fallback"
  └── Added offline_sim.py for rule-based simulation when LLM unavailable
  └── Plan/Command dual-mode architecture (strategic intent vs execution)
  └── Problem: Two code paths, inconsistent results
  └── Lesson: Fallback ≠ foundation

v0.3 (2026-06)  "Engine First, LLM as Narrator"
  └── Core insight: "LLM is the multiplier, not the base"
  └── Three-layer accountability model:
      Layer 1 (Hard Engine, Python) — MUST be correct (physics, combat, economy)
      Layer 2 (Soft Rules, YAML)   — CAN be fuzzy (morale, loyalty, events)
      Layer 3 (LLM Narrative)      — MAY be dramatic (story, dialogue, atmosphere)
  └── Lesson: Correct architecture, but execution gap (17 docs vs empty character data)

v2.0 (2026-06)  "Seven-Engine Architecture"
  └── Modular engines: Map, Character, Domestic, Military, Decision, History, Narrative
  └── Rules-as-Data: YAML configuration replaces hardcoded Python logic
  └── histrategy-engine (pure Python, zero LLM) + histrategy-knowledge (pure data)
  └── SimPly v2 pluggable framework: add a governance system = write 2 YAML files
  └── Current status: architecture validated (351 tests), awaiting content fill
```

### 1.2 Core Design Principles

| Principle | Description |
|-----------|-------------|
| **Engine 不能错** | 粮食=种植面积×产量×气候。这是物理定律，不容 LLM 篡改。 |
| **Rules 可以调** | 忠诚度衰减速率、税率对民心的影响 — 这些用 YAML 配置，社区可贡献。 |
| **Narrative 可以夸张** | "诸葛亮妙计退兵" — LLM 可以渲染气氛，但不能凭空创造兵力。 |
| **History as Gravity** | 历史事件有"引力值"(gravity)。结构性矛盾事件（如荆州地缘冲突）引力极高，个人决策难以改变。 |
| **Rules are Data, not Code** | 加一个合法性系统：v1 改 4-6h Python；v2 写 2 个 YAML 文件 15 分钟。 |
| **正史优先，演义可选** | 数据源优先级：《三国志》裴注 > 《资治通鉴》 > 《后汉书》 > 《三国演义》。 |

### 1.3 Lessons from Competitors

**From 《崇祯模拟器》 (2026-05)**:
- ✅ Validated the market: players will pay for LLM historical strategy games
- ✅ LLM narrative immersion is powerful — we should aim for this quality
- ❌ Pure LLM architecture → fairness issues (AI says "圣明" but tax is 90%)
- ❌ Locked API + Token monetization → 55% Steam approval, massive backlash
- **Takeaway**: 崇祯不是"错误的架构"——是"极端的架构"在"错误的商业模式"上执行

**From 光荣《三国志》11/14**:
- ✅ Complete economic cycle (金→兵→战→地→金) — we need this
- ✅ ROTK 11 survived 20 years because of MOD community — our YAML rules market can surpass this
- ❌ Hardcoded engine, limited modding → our Rules-as-Data beats this
- ❌ No natural language, no narrative depth → our LLM layer fills this gap

---

## 2. Architecture Roadmap

### Phase 1: Engine Foundation (Current)

> **Goal**: Fill the gap between architecture and playability.

| Priority | Task | Status | Est. |
|----------|------|--------|------|
| P0 | Grain system integration (粮食→兵→战闭环) | 🔴 Not started | 3h |
| P0 | Legitimacy/prestige system (合法性→忠诚→人才) | 🔴 Not started | 4h |
| P0 | Character data population (角色五维+关系网) | 🔴 Not started | 2h |
| P1 | Appointment/enfeoffment system (分封任命) | 🔴 Not started | 2h |
| P1 | v1/v2 architecture unification (统一入口) | 🔴 Not started | 2h |
| P2 | Historical anchor events with gravity scores | 🔴 Not started | 3h |

### Phase 2: Narrative & Feedback Loop

> **Goal**: Make the game "feel" immersive, not just correct.

| Priority | Task | Status |
|----------|------|--------|
| P0 | Progress visualization (进度条 + 趋势 sparklines) | 🔴 Not started |
| P0 | "Chronicle entry" (史官注) for divergence moments | 🔴 Not started |
| P1 | Character biographies on death/betrayal (陈寿评语格式) | 🔴 Not started |
| P1 | NPC emotional state + betrayal arcs | 🔴 Not started |
| P2 | Player style profiling + adaptive advisors | 🔴 Not started |
| P2 | Retrospective narrator at game end | 🔴 Not started |

### Phase 3: Agent Clients & Web

> **Goal**: Reach players beyond the terminal.

| Priority | Task | Status |
|----------|------|--------|
| P0 | REST API (FastAPI) — headless engine wrapper | 🔴 Not started |
| P0 | Web client MVP at emergence.science/playground/histrategy | 🔴 Not started |
| P1 | Feishu Agent Skill (飞书群聊即游戏房) | 🔴 Not started |
| P1 | OpenClaw Skill Package (ClawHub 发布) | 🔴 Not started |
| P2 | Discord bot integration | 🔴 Not started |
| P2 | Recording pipeline (headless → frames → ffmpeg → demo.mp4) | 🔴 Not started |

### Phase 4: Community & Ecosystem

> **Goal**: From "one game" to "a thousand games on one framework".

| Priority | Task | Status |
|----------|------|--------|
| P0 | histrategy-knowledge YAML migration (社区可编辑) | 🔴 Not started |
| P1 | YAML rules marketplace (SimPly v2) | 🔴 Not started |
| P1 | Community contribution pipeline (角色数据、历史事件、规则) | 🔴 Not started |
| P2 | Alternative scenario support (战国七雄、罗马帝国) | 🔴 Not started |
| P2 | Multiplayer mode (群聊多人对抗/合作) | 🔴 Not started |

---

## 3. Community Contribution Model

Four levels, all zero-code except Level 4:

```
Level 4: New Game Backgrounds (需要开发能力)
  哈利波特 / 红色警戒 / 罗马帝国 / 战国七雄
  = 完整规则集 + 知识库 + LLM prompts

Level 3: Rule Modifications (只需编辑 YAML)
  "让骑兵更强" / "屯田效果翻倍" / "增加外交系统"
  = YAML 规则文件修改

Level 2: Historical Data (只需编辑 YAML/JSON)
  "添加蔡文姬角色数据" / "补充 219 年事件链"
  = 知识库数据贡献

Level 1: Game Replays & Videos (所有玩家)
  "我的刘备统一天下存档" / B站游戏视频
  = 存档分享 + 视频上传
```

### Knowledge Base Format (histrategy-knowledge)

All data in YAML with source attribution:

```yaml
# characters/guan_yu.yaml
id: guan_yu
name: 关羽
source: "三国志·关羽传"
stats:
  leadership: 92
  might: 95
  intelligence: 65
  politics: 40
  charisma: 88
personality:
  weakness: "刚而自矜，以短取败"  # 陈寿原评
```

---

## 4. Web Version Strategy

Hosted at `emergence.science/playground/histrategy`:

| Tier | Access | LLM Cost |
|------|--------|----------|
| **Demo** | 10 回合体验，无需注册 | ~$0.07/user (platform subsidized) |
| **Free** | 注册用户，每月 50 回合 | ~$0.35/user/month |
| **BYOK** | 自带 API Key，无限制 | $0 (user pays own LLM) |
| **Pro** | emergence.science 会员 | Bundled with membership |

Server stores game saves; shareable via URL (`?game=abc123`).

---

## 5. Target Audience & Go-to-Market

### Primary Audience (🎯 Focus)

| Segment | Core Need | Channel |
|---------|-----------|---------|
| 25-40 历史+策略爱好者 | 在策略游戏中理解历史深层逻辑 | 知乎专栏、B站中长视频 |
| 开发者/技术人 | 开源可拔插的 LLM 游戏引擎 | Hacker News, GitHub, V2EX |

### Secondary Audience

| Segment | Core Need | Channel |
|---------|-----------|---------|
| 学生/年轻人 | 好玩 + 能学到历史 | B站短视频、小红书 |
| 学术界 | 可控实验的仿真平台 | arXiv、AIIDE/FDG/CHI 会议 |

### Positioning (一句话)

> *给懂历史的成年人玩的三国策略游戏 — 不是简单的选择题，不是 AI 胡说八道，而是在物理引擎上的严肃推演。*

---

## 6. Academic Paper Plan

**Working Title**: "SimPly: A Layered Architecture for Deterministic Simulation with LLM Narrative in Strategy Games"

**Core Contributions**:
1. Three-layer accountability model (Engine / Rules / Narrative)
2. Rules-as-Data (YAML configurable vs hardcoded)
3. Spec-Driven testing from behavioral specifications
4. Historical gravity model (gravity + deviation event triggering)
5. Comparative case study: Chongzhen Simulator's pure-LLM failure modes

**Target Venues**: AIIDE, FDG, CHI Games Track
**Timeline**: Draft 3 months after Phase 2 completion. `docs/design-iterations.md` is the running research log.

---

## 7. Milestone Summary

| Version | Key Deliverable | ETA |
|---------|----------------|-----|
| **v0.3** | Engine foundation filled (grain, legitimacy, characters, appointments) | 1 week |
| **v0.4** | Narrative feedback loop (progress viz, chronicle entries, NPC drama) | +2 weeks |
| **v0.5** | Web client MVP at emergence.science | +2 weeks |
| **v0.6** | Agent clients (Feishu, Discord) + multiplayer | +3 weeks |
| **v1.0** | Community rules marketplace + alternative scenarios | +2 months |
| **Paper** | Academic preprint submission | +3 months from v0.5 |

---

## Document Index

| Document | Description | Status |
|----------|-------------|--------|
| `ROADMAP.md` | This document — strategic roadmap | ✅ Current |
| `design-iterations.md` | Design evolution log + academic material | ✅ Current |
| `architecture-philosophy.md` | Core design philosophy | ✅ Current |
| `design-v2-technical-spec.md` | Seven-engine architecture specification | ✅ Current |
| `design-v2-physics-engine.md` | Physics engine core + anti-injection | ✅ Current |
| `design-v2-implementation-plan.md` | Implementation plan + TDD + rollback | ✅ Current |
| `simply-v2-pluggable-framework.md` | YAML rules-as-data framework | ✅ Current |
| `governance-engine-design.md` | Governance system design | ✅ Current |
| `design-p5-web-recording.md` | Web client + video recording pipeline | ✅ Current |
| `PRD-openclaw.md` | OpenClaw/Hermes integration PRD | ✅ Current |
| `tech-design-openclaw.md` | OpenClaw technical design | ✅ Current |
| `tech-design-agent-clients.md` | Multi-platform agent client design | ✅ Current |
| `OPERATIONS.md` | DevOps & contributor operations | ✅ Current |
| `archive/PRD.md` | v0.2 PRD | 📦 Archived |
| `archive/tech-design.md` | v0.3 tech design | 📦 Archived |
| `archive/simply-v1-framework.md` | SimPly v1 framework | 📦 Archived |
