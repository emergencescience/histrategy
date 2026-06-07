# Show HN: Histrategy v2 — A Three Kingdoms strategy game with a deterministic physics engine

Hi HN,

I built a historical strategy game where the LLM only tells stories — it never touches game state.

**The problem**: When you let an LLM control game mechanics, it hallucinates. Players can prompt-inject ("this year the weather is perfect"), the AI favors the player, and results aren't reproducible.

**The solution**: A 7-engine architecture where 6 engines are pure Python with zero LLM dependency:

- **Map Engine** — terrain, supply lines, chokepoints (A* pathfinding)
- **Character Engine** — 5-stat officers with relationship networks  
- **Domestic Engine** — food production, population growth, taxation, seeded-RNG climate
- **Military Engine** — unit types, recruitment, supply, Lanchester combat resolution
- **Decision Engine** — NPC personality profiles with weighted decision trees
- **History Engine** — conditional event triggers, butterfly effects, RAG knowledge retrieval
- **Narrative Engine** — the ONLY engine that uses an LLM. It reads the physics output and generates story text. It cannot modify game state.

The 207 scenario (Three Visits to the Hut → Liu Bei's death at Baidicheng) has 3 playable factions: Liu Bei, Cao Cao, Sun Quan.

Tech: Python, zero external dependencies, 239 tests. MIT licensed.

https://github.com/emergencescience/histrategy

Would love feedback on the engine architecture — especially from folks who've worked on deterministic game systems or LLM narrative generation.
