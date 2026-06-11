# Show HN: Histrategy v2 — LLMs tell the story, a physics engine runs the game

Hi HN,

I built an open-source Three Kingdoms strategy game where you command armies in natural language — but the LLM only writes the narrative. All game mechanics run on a deterministic physics engine.

**Why**: When you let an LLM control game state, three things break: (1) players can prompt-inject ("the weather is perfect this year"), (2) the AI favors the player over NPCs, (3) results aren't reproducible — you can't test or balance.

**Architecture**: 7 engines. 6 are pure Python. 1 uses an LLM (read-only):

| Engine | Does | How |
|--------|------|-----|
| Map | Terrain, supply lines, chokepoints | A* pathfinding |
| Character | Officer stats, loyalty, death | Probability model |
| Domestic | Food, population, tax, climate | YAML formula + seeded RNG |
| Military | Recruitment, supply, combat | Lanchester equations |
| Decision | NPC behavior | Weighted decision trees (Cao Cao: aggression=0.8) |
| History | Events, butterfly effects | Conditional triggers × gravity |
| Narrative | Story generation | **LLM (read-only, cannot modify state)** |

The key insight: NPC orders and player orders are the same `Command(type="attack", params={...})` format. The physics engine doesn't know who's human. This eliminates AI favoritism.

**What's playable**: 207 AD scenario (Three Visits to the Hut → Baidicheng). Three factions: Cao Cao (150K troops), Sun Quan (60K), Liu Bei (5K — hard mode). Real players have reached turn 19.

**Rules-as-Data**: All game formulas live in YAML, not code. You can change balance without touching Python — we're exploring a "rule marketplace" where the community proposes and tests rule patches.

**Stack**: Python, 459 tests, MIT license. [Player manual](https://emergence.science/games/histrategy/manual). Play at [emergence.science/games/histrategy](https://emergence.science/games/histrategy).

**Repo**: https://github.com/emergencescience/histrategy

Feedback welcome — especially from folks who've built deterministic game systems or LLM narrative pipelines.
