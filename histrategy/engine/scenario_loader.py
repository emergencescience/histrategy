"""
ScenarioLoader — unified scenario data loader for the Scenarios/{id}/ directory.

Replaces the ad-hoc loader functions with a single class that reads from the
standardised scenarios/ directory structure:

    scenarios/{scenario_id}/
        scenario.toml          — engine & faction config
        knowledge/
            territories.json   — map territories
            factions.json      — faction definitions (array or dict)
            characters.json    — character roster
            events.json        — scripted/historical events
            initial_state.json — full initial WorldState snapshot
        prompts/
            system.md          — system prompt template
            ...
        rules/
            *.yaml             — rule configuration files

For backwards compatibility, when a scenario does not yet have its own data
files the loader falls back to the three-kingdoms scenario knowledge.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import tomllib
from histrategy_engine.world import (
    Army,
    Character,
    FactionState,
    Season,
    TerrainType,
    Territory,
    UnitType,
    WorldState,
)

logger = __import__("logging").getLogger(__name__)

from .loader import (
    TERRAIN_MAP,
    _default_characters,
    _default_factions,
    _find_scenarios_root,
    _territory_from_json,
    resolve_knowledge_path,
)
from .loader import (
    load_characters as _legacy_load_characters,
)

# ─── helpers ────────────────────────────────────────────────────────────────

# Canonical scenario directory names.  Any other value is rejected with a
# clear error — legacy numeric IDs (e.g. "207" for three-kingdoms)
# alias must be replaced with the canonical names.


def _validate_scenario_id(scenario_id: str) -> str:
    """Validate and return a canonical scenario ID.

    Raises ValueError if *scenario_id* is not a known canonical name.
    """
    if scenario_id not in ("three-kingdoms", "rome-triumvirate", "nanming"):
        raise ValueError(
            f"Unknown scenario {scenario_id!r}. "
            f"Expected one of: 'three-kingdoms', 'rome-triumvirate'"
        )
    return scenario_id


def _coerce_factions_to_dict(data: list | dict) -> dict:
    """Normalise faction data to a dict keyed by faction id.

    Supports both the array format (rome-triumvirate) and the legacy dict format.
    """
    if isinstance(data, dict):
        return data
    result: dict = {}
    for item in data:
        fid = item.get("id", item.get("name", ""))
        if fid:
            result[fid] = item
    return result


# ─── ScenarioLoader ─────────────────────────────────────────────────────────


class ScenarioLoader:
    """Load scenario data from scenarios/{id}/ directory.

    Usage::

        loader = ScenarioLoader("three-kingdoms")
        ws = loader.build_world_state("shu")

        loader2 = ScenarioLoader("rome-triumvirate")
        ws2 = loader2.build_world_state("octavian")
    """

    def __init__(
        self,
        scenario_id: str = "three-kingdoms",
        scenarios_root: Path | None = None,
    ):
        # Validate scenario ID against known canonical names
        self.scenario_id = _validate_scenario_id(scenario_id)
        self._root = scenarios_root or _find_scenarios_root()
        self._dir = self._root / self.scenario_id
        self._toml = self._load_toml()

    # ── TOML config ─────────────────────────────────────────────────────

    def _load_toml(self) -> dict:
        """Load scenario.toml, returning an empty dict if it doesn't exist."""
        toml_path = self._dir / "scenario.toml"
        if toml_path.is_file():
            with open(toml_path, "rb") as f:
                return tomllib.load(f)
        return {}

    @property
    def year_direction(self) -> str:
        """'positive' (AD) or 'negative' (BC)."""
        engine = self._toml.get("engine", {})
        return engine.get("year_direction", "positive")

    @property
    def available_factions(self) -> list[str]:
        """Player-selectable faction IDs from TOML config."""
        factions_cfg = self._toml.get("factions", {})
        return list(factions_cfg.get("available", []))

    @property
    def npc_only_factions(self) -> list[str]:
        """NPC-only faction IDs from TOML config."""
        factions_cfg = self._toml.get("factions", {})
        return list(factions_cfg.get("npc_only", []))

    @property
    def max_quarters(self) -> int:
        """游戏最大季度数（剧终阈值）。0 表示不限制。

        scenario.toml 的 [engine] max_quarters。到该季度后游戏进入终局
        （强制剧终 + 历史偏移结算）。此前该字段定义了但从未被 enforce。
        """
        engine = self._toml.get("engine", {})
        try:
            return int(engine.get("max_quarters", 0) or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def major_npc_factions(self) -> list[str]:
        """独立 LLM 决策的主要 AI 势力（scenario.toml [factions] major_npc）。"""
        factions_cfg = self._toml.get("factions", {})
        return list(factions_cfg.get("major_npc", []))

    @property
    def declared_factions(self) -> list[str]:
        """剧本 `[factions]` 里声明过的**全部**势力 id。

        用于校验 `faction` 参数属于该剧本（`/api/single-player/start`）。
        比 `available_factions` 宽 —— 含 major_npc / minor_npc / npc_only，
        因为玩家理论上可以选任何一个在剧本里有数据的势力；这里挡的是
        「在罗马房间里传 `shu`」这种跨剧本串味。
        """
        factions_cfg = self._toml.get("factions", {})
        ordered: list[str] = []
        for key in ("available", "major_npc", "minor_npc", "npc_only"):
            for fid in factions_cfg.get(key, []) or []:
                if fid not in ordered:
                    ordered.append(fid)
        return ordered

    @property
    def settled_factions(self) -> list[str]:
        """每回合需要结算状态的势力 = `available` ∪ `major_npc`。

        用户 2026-10-04 裁定：**罗马 4 个、三国 3 个**势力需要每回合结算，
        其余（minor_npc / npc_only，如罗马的 sextus_pompey、三国的 liubiao
        & liuzhang）是"世界布景"—— 他们持有静态驻军，但 LLM 不为他们决策，
        引擎替他们算出来的任何漂移都是噪音。

        实测口径：
          rome-triumvirate  available=[octavian,antony,cleopatra,senate] → 4
          three-kingdoms     available=[cao,shu,wu]                       → 3
          nanming            available=[nanming,qing,nongminjun,zheng]     → 4
        返回空列表表示"全部结算"（向后兼容）。
        """
        ordered: list[str] = []
        for fid in self.available_factions + self.major_npc_factions:
            if fid not in ordered:
                ordered.append(fid)
        return ordered

    @property
    def map_topology(self) -> str:
        """地图拓扑，来自 scenario.toml 的 [engine] map_topology。

        "adjacency"      —— 默认。按 territories.json 的 `neighbors` 字段走图论，
                            缺 `neighbors` 的地块就是孤岛。
        "fully_connected"—— 全连通。用于**以地中海为交通主干**的剧本：海上运输
                            远比陆运便宜，所以罗马世界的所有行省彼此可达，不存
                            "不相邻所以打不到"这回事。（用户 2026-10-04 裁定：
                            罗马地图不需要边。）
        """
        engine = self._toml.get("engine", {})
        return str(engine.get("map_topology", "adjacency") or "adjacency")

    def _apply_map_topology(self, territories: dict) -> None:
        """按 map_topology 物化地图邻接关系（就地修改 Territory.neighbors）。

        为什么在 loader 里物化成稠密图、而不是改 MapEngine：
        MapEngine 是通用组件，不认识剧本；把"罗马靠海全连通"这条**剧本知识**
        放进剧本配置 + loader，MapEngine 保持原样即可 —— 同时保证
        `are_adjacent()` / `get_neighbors()` / 攻城邻接校验
        (`state_applier._attacker_borders_territory`) 这些**已有**的下游逻辑
        无需任何改动就能正确工作。
        """
        if self.map_topology != "fully_connected" or not territories:
            return
        all_ids = list(territories.keys())
        for tid, t in territories.items():
            t.neighbors = [other for other in all_ids if other != tid]
        logger.info(
            "[scenario=%s] map_topology=fully_connected → %d territories, %d directed edges",
            self.scenario_id,
            len(all_ids),
            len(all_ids) * (len(all_ids) - 1),
        )

    # ── public data loaders ─────────────────────────────────────────────

    def load_factions(self) -> dict:
        """Read knowledge/factions.json (array or dict format).

        Falls back to initial_state.json factions if factions.json is missing.
        """
        # 1) Try knowledge/factions.json
        factions_path = self._dir / "knowledge" / "factions.json"
        if factions_path.is_file():
            with open(factions_path, encoding="utf-8") as f:
                return _coerce_factions_to_dict(json.load(f))

        # 2) Try initial_state.json factions key
        init = self.load_initial_state()
        if init and "factions" in init:
            return _coerce_factions_to_dict(init["factions"])

        # 3) Try legacy scenario JSON via loader
        try:
            from .loader import load_scenario as _legacy_load_scenario

            scenario = _legacy_load_scenario(self.scenario_id)
            if scenario and "factions" in scenario:
                return scenario["factions"]
        except Exception:
            pass

        # 4) Fall back to hardcoded defaults
        return _default_factions()

    def load_characters(self) -> dict[str, Character]:
        """Read knowledge/characters.json.

        Falls back to the legacy loader when the file is missing.
        """
        char_path = self._dir / "knowledge" / "characters.json"
        if char_path.is_file():
            with open(char_path, encoding="utf-8") as f:
                data = json.load(f)

            # Support both array and {"characters": [...]} formats
            items = data if isinstance(data, list) else data.get("characters", [])

            characters: dict[str, Character] = {}
            for cd in items:
                if isinstance(cd, dict):
                    char = _character_from_dict(cd)
                    characters[char.id] = char
            if characters:
                return characters

        # Fall back to legacy loader
        try:
            return _legacy_load_characters()
        except Exception:
            return _default_characters()

    def load_territories(self) -> dict[str, Territory]:
        """Read knowledge/territories.json.

        Uses the same code path as the P0.3 refactored load_territories().
        """
        territory_path = self._dir / "knowledge" / "territories.json"

        # Fallback: try three-kingdoms if this scenario doesn't have its own
        if not territory_path.is_file() and self.scenario_id != "three-kingdoms":
            fallback = self._root / "three-kingdoms" / "knowledge" / "territories.json"
            if fallback.is_file():
                territory_path = fallback

        if not territory_path.is_file():
            # Last resort: try old knowledge_path
            try:
                kp = resolve_knowledge_path()
                old_path = Path(kp) / "territories.json"
                if old_path.is_file():
                    territory_path = old_path
            except Exception:
                pass

        if not territory_path.is_file():
            raise FileNotFoundError(f"Cannot find territories.json for scenario '{self.scenario_id}'")

        with open(territory_path, encoding="utf-8") as f:
            data = json.load(f)

        territories: dict[str, Territory] = {}
        for td in data:
            t = _territory_from_json(td)
            territories[t.id] = t
        return territories

    def load_initial_state(self) -> dict | None:
        """Read knowledge/initial_state.json."""
        init_path = self._dir / "knowledge" / "initial_state.json"
        if init_path.is_file():
            with open(init_path, encoding="utf-8") as f:
                return json.load(f)
        return None

    def load_prompt(self, name: str = "system") -> str:
        """Read prompts/{name}.md."""
        prompt_path = self._dir / "prompts" / f"{name}.md"
        if prompt_path.is_file():
            return prompt_path.read_text(encoding="utf-8")

        # Fallback: try old prompt_loader
        try:
            from histrategy.llm.prompt_loader import load_prompt as _load_prompt

            return _load_prompt(name)
        except Exception:
            pass

        raise FileNotFoundError(f"No prompt '{name}.md' in {self._dir / 'prompts'} and no fallback available")

    def load_rules(self) -> list[Path]:
        """List rules/*.yaml files in the scenario directory."""
        rules_dir = self._dir / "rules"
        if not rules_dir.is_dir():
            return []
        return sorted(rules_dir.glob("*.yaml"))

    # ── world state assembly ────────────────────────────────────────────

    def build_world_state(self, player_faction_id: str) -> WorldState:
        """Assemble a complete WorldState from scenario data.

        For scenarios with an initial_state.json this is the canonical path;
        otherwise falls back to the legacy build_world_state() codepath.
        """
        # Load territories and characters
        territories = self.load_territories()
        characters = self.load_characters()

        # Materialize the scenario's map topology (e.g. "fully_connected" for
        # Mediterranean scenarios). Must happen BEFORE the WorldState is built
        # so every downstream consumer — MapEngine, the attack-adjacency guard
        # in state_applier — sees the real graph on the very first turn.
        self._apply_map_topology(territories)

        # Try initial_state.json first (modern path)
        init = self.load_initial_state()
        if init and "factions" in init:
            return self._build_from_initial_state(init, player_faction_id, territories, characters)

        # Legacy path: build from scenario JSON
        from .loader import load_scenario as _legacy_load_scenario

        scenario = _legacy_load_scenario(self.scenario_id)
        knowledge_path = resolve_knowledge_path()

        return self._build_from_legacy_scenario(scenario, player_faction_id, territories, characters, knowledge_path)

    def _build_from_initial_state(
        self,
        init: dict,
        player_faction_id: str,
        territories: dict[str, Territory],
        characters: dict[str, Character],
    ) -> WorldState:
        """Build WorldState from a modern initial_state.json."""
        factions_data = _coerce_factions_to_dict(init.get("factions", {}))
        factions = self._build_factions(factions_data)

        # Override territory ownership from faction data
        for fid, faction in factions.items():
            for tid in faction.territories:
                if tid in territories:
                    territories[tid].owner_id = fid

        # Apply territory overrides from initial_state (population, development, fertility, etc.)
        init_territories = init.get("territories", {})
        if init_territories:
            for tid, td in init_territories.items():
                if tid in territories:
                    t = territories[tid]
                    if "name" in td:
                        t.name = td["name"]
                    if "population" in td:
                        t.population = td["population"]
                    if "development" in td:
                        t.development = td["development"]
                    if "terrain" in td:
                        from ..engine.loader import TERRAIN_MAP

                        t.terrain_type = TERRAIN_MAP.get(td["terrain"], t.terrain_type)
                    if "climate_zone" in td:
                        t.climate_zone = td["climate_zone"]
                    if "fertility" in td:
                        t.fertility = td["fertility"]
                    # ── 声明式归属（initial_state.territories[*].owner）──
                    # 上面那段只从 `factions[*].territories` 反推归属，而本文件每个
                    # territory 都带一个 `owner` 字段 —— 该字段此前**从未被读取**：
                    # 改了它什么也不会发生（死数据）。后果是数据写着「汉中属农民军」
                    # 而引擎里汉中无主；rome 剧本同理丢掉 4 块（sicilia/sardinia 属
                    # 庞培之子、africa/transalpine_gaul 属安东尼）。
                    # 现在以该声明字段为准，与 factions 列表真正矛盾时打警告而非静默择一。
                    _declared = td.get("owner")
                    if _declared:
                        _cur = getattr(t, "owner_id", "") or ""
                        if _cur and _cur != _declared:
                            logger.warning(
                                "[scenario=%s] territory %s 归属冲突：factions 列表=%s ≠ "
                                "initial_state.owner=%s —— 以 initial_state.owner 为准",
                                self.scenario_id, tid, _cur, _declared,
                            )
                        t.owner_id = _declared

        # ── Sync faction.territories ← territory.owner_id (2026-10-04) ──
        # The two sources disagree after the block above: `initial_state.json`'s
        # per-territory `owner` field is authoritative and is applied LAST, but it
        # never updated `factions[*].territories`. Measured on rome: 5 territories
        # desynced (antony held italia/africa/transalpine_gaul, sextus_pompey held
        # sicilia/sardinia — none of them listed in the owner's `territories`).
        # Consequence: `faction.territories` (what the UI / game_state shows) lied
        # about ownership while the map, movement and battle logic used owner_id —
        # and it made the two population computation paths return DIFFERENT numbers
        # for the same faction. Same de-sync class that `_sync_faction_territories`
        # repairs mid-game in room_manager; do the equivalent once at load time so
        # the WorldState starts coherent.
        _owner_map: dict[str, list[str]] = {}
        for _tid, _t in territories.items():
            _own = getattr(_t, "owner_id", "") or ""
            if _own:
                _owner_map.setdefault(_own, []).append(_tid)
        for _fid, _faction in factions.items():
            _synced = sorted(_owner_map.get(_fid, []))
            if _synced != sorted(_faction.territories):
                logger.warning(
                    "[scenario=%s] faction %s territories desync → synced from owner_id: %s → %s",
                    self.scenario_id, _fid, sorted(_faction.territories), _synced,
                )
                _faction.territories = _synced

        # Determine season
        season_str = init.get("season", "spring")
        season = _parse_season(season_str)

        # Determine year
        year = init.get("year", 207)
        # Apply TOML override
        toml_meta = self._toml.get("meta", {})
        if "start_year" in toml_meta:
            year = toml_meta["start_year"]

        # Create armies
        armies = self._create_armies(factions)

        # Compute faction.population.
        # 2026-10-04: a faction may DECLARE its own population (retainers /
        # clients / 家丁) — population is a faction-level attribute, not merely a
        # derived sum of territory populations. Rome-era populations were not
        # bound to land: a clientela could follow its patron. So a landless
        # faction keeps its declared population rather than collapsing to 0.
        #   - landed faction, no declaration → territory sum (unchanged legacy)
        #   - landed faction + declaration   → the larger of the two
        #   - landless faction + declaration → the declaration
        for fid, faction in factions.items():
            declared_pop = int(getattr(faction, "population_floor", 0) or 0)
            pop_sum = sum(
                getattr(territories[tid], "population", 0)
                for tid in faction.territories
                if tid in territories
            )
            faction.population = max(declared_pop, pop_sum)

        return WorldState(
            year=year,
            season=season,
            turn_number=1,
            scenario=self.scenario_id,
            player_faction_id=player_faction_id,
            territories=territories,
            characters=characters,
            factions=factions,
            armies=armies,
            player_deviation=0.0,
            settled_faction_ids=self.settled_factions,
        )

    def _build_from_legacy_scenario(
        self,
        scenario: dict | None,
        player_faction_id: str,
        territories: dict[str, Territory],
        characters: dict[str, Character],
        knowledge_path: str,
    ) -> WorldState:
        """Build WorldState from legacy scenario JSON."""
        # Apply territory overrides from scenario
        if scenario and "territories" in scenario:
            for tid, td in scenario["territories"].items():
                if tid in territories:
                    t = territories[tid]
                    if "name" in td:
                        t.name = td["name"]
                    if "population" in td:
                        t.population = td["population"]
                    if "development" in td:
                        t.development = td["development"]
                    if "terrain" in td:
                        t.terrain_type = TERRAIN_MAP.get(td["terrain"], TerrainType.PLAINS)
                    if "climate_zone" in td:
                        t.climate_zone = td["climate_zone"]
                    if "fertility" in td:
                        t.fertility = td["fertility"]

        # Determine season
        season = Season.SPRING
        if scenario:
            season_str = scenario.get("season", "winter")
            season = _parse_season(season_str)

        # Build factions
        factions: dict[str, FactionState] = {}
        if scenario and "factions" in scenario:
            factions = self._build_factions(scenario["factions"])
        else:
            factions = _default_factions()

        # Assign territory ownership from faction data
        for fid, faction in factions.items():
            for tid in faction.territories:
                if tid in territories:
                    territories[tid].owner_id = fid

        # Create armies
        armies = self._create_armies(factions)

        # Compute faction.population from territory sums (same fix as _build_from_initial_state)
        for fid, faction in factions.items():
            pop_sum = sum(
                getattr(territories[tid], "population", 0)
                for tid in faction.territories
                if tid in territories
            )
            if pop_sum > 0:
                faction.population = pop_sum

        return WorldState(
            year=scenario.get("year", 207) if scenario else 207,
            season=season,
            turn_number=1,
            scenario=self.scenario_id,
            player_faction_id=player_faction_id,
            territories=territories,
            characters=characters,
            factions=factions,
            armies=armies,
            player_deviation=0.0,
            settled_faction_ids=self.settled_factions,
        )

    def _build_factions(self, factions_data: dict) -> dict[str, FactionState]:
        """Build FactionState objects from raw dict data.

        Handles both legacy TK field names and modern rome-triumvirate field names.
        """
        factions: dict[str, FactionState] = {}
        for fid, fd in factions_data.items():
            personality = fd.get("personality", {})

            # Support both `territories` (legacy) and `starting_territories` (caesar)
            faction_territories = list(fd.get("territories", fd.get("starting_territories", [])))

            factions[fid] = FactionState(
                id=fid,
                name=fd.get("name", fid),
                ruler_id=fd.get("ruler", fd.get("ruler_id", "")),
                name_en=fd.get("name_en", ""),
                capital=fd.get("capital", ""),
                territories=faction_territories,
                is_active=fd.get("is_active", fd.get("is_active_manually", True)),
                prestige=fd.get("prestige", 50),
                legitimacy=fd.get("legitimacy", 50),
                strength_actual=fd.get("strength_actual", fd.get("strength", 5000)),
                economy_actual=fd.get("economy_actual", fd.get("economy", 50)),
                morale_actual=fd.get("morale_actual", fd.get("morale", 50)),
                treasury=fd.get("treasury", 5000),
                food=fd.get("food", 3000),
                # 2026-10-04: population MUST be read here. It previously was not
                # passed at all, so a scenario declaring `population` in
                # initial_state.json silently lost it (declaration was a no-op)
                # and landless factions were stuck at the dataclass default.
                # population = 家丁/门客下限（见 FactionState.population_floor）
                population=fd.get("population", 0),
                population_floor=fd.get("population", 0),
                off_territory_income=fd.get("off_territory_income", 0.0),
                off_territory_food=fd.get("off_territory_food", 0.0),
                tax_rate=fd.get("tax_rate", 0.3),
                tech_levels=fd.get("tech_levels", {}),
                relations=fd.get("relations", {}),
                aggression=personality.get("aggression", fd.get("aggression", 0.5)),
                cunning=personality.get("cunning", fd.get("cunning", 0.5)),
                caution=personality.get("caution", fd.get("caution", 0.5)),
                diplomacy=personality.get("diplomacy", fd.get("diplomacy_tendency", 0.5)),
                development_focus=personality.get("development", fd.get("development_focus", 0.5)),
                mercy=personality.get("mercy", fd.get("mercy", 0.5)),
            )

        # ── Build allies list from mutual positive relations ──
        # Relations >= ALLIANCE_THRESHOLD are considered allies.
        # Alliance is mutual: if nanming→zheng >= 30 AND zheng→nanming >= 30,
        # both get each other in their allies list.
        ALLIANCE_THRESHOLD = 20
        for fid, fs in factions.items():
            for other_fid, rel in fs.relations.items():
                other = factions.get(other_fid)
                if other and rel >= ALLIANCE_THRESHOLD:
                    other_rel = other.relations.get(fid, 0)
                    if other_rel >= ALLIANCE_THRESHOLD:
                        if other_fid not in fs.allies:
                            fs.allies.append(other_fid)

        return factions

    def _create_armies(self, factions: dict[str, FactionState]) -> dict[str, Army]:
        """Create initial armies for active factions.

        Troops are spread proportionally across territories with faction-specific
        unit compositions that reflect historical military capabilities.
        """
        # ── Faction-specific unit compositions ──
        _FACTION_UNIT_COMP: dict[str, dict[UnitType, float]] = {
            # Nanming
            "qing":         {UnitType.CAVALRY: 0.40, UnitType.INFANTRY: 0.40, UnitType.ARCHER: 0.20},
            "nanming":      {UnitType.INFANTRY: 0.55, UnitType.ARCHER: 0.30, UnitType.CAVALRY: 0.15},
            "nongminjun":   {UnitType.INFANTRY: 0.85, UnitType.ARCHER: 0.15},
            "zheng":        {UnitType.NAVY: 0.35, UnitType.INFANTRY: 0.40, UnitType.ARCHER: 0.25},
            # Three Kingdoms
            "cao":          {UnitType.CAVALRY: 0.35, UnitType.INFANTRY: 0.45, UnitType.ARCHER: 0.20},
            "wu":           {UnitType.NAVY: 0.30, UnitType.ARCHER: 0.30, UnitType.INFANTRY: 0.40},
            "shu":          {UnitType.INFANTRY: 0.55, UnitType.ARCHER: 0.25, UnitType.CAVALRY: 0.20},
            "liubiao":      {UnitType.NAVY: 0.20, UnitType.INFANTRY: 0.55, UnitType.ARCHER: 0.25},
            "liuzhang":     {UnitType.INFANTRY: 0.70, UnitType.ARCHER: 0.30},
        }
        _FACTION_TRAINING: dict[str, float] = {
            "qing": 1.3, "nanming": 0.9, "nongminjun": 0.6, "zheng": 1.0,
            "cao": 1.2, "wu": 1.0, "shu": 0.85, "liubiao": 0.7, "liuzhang": 0.5,
        }
        _FACTION_MORALE: dict[str, int] = {
            "qing": 85, "nanming": 70, "nongminjun": 75, "zheng": 80,
            "cao": 80, "wu": 75, "shu": 85, "liubiao": 55, "liuzhang": 45,
        }

        armies: dict[str, Army] = {}
        army_idx = 1
        for fid, faction in factions.items():
            if not faction.is_active or not faction.territories:
                continue

            num_territories = len(faction.territories)
            if num_territories <= 0:
                num_territories = 1

            comp = _FACTION_UNIT_COMP.get(fid, {UnitType.INFANTRY: 1.0})
            training = _FACTION_TRAINING.get(fid, 1.0)
            base_morale = _FACTION_MORALE.get(fid, 80)

            # Deploy the FULL faction strength, spread across territories
            # H37c-fix: the old `min(..., 30000)` cap silently dropped troops for
            # factions with few territories + large armies (e.g. nongminjun 90k in
            # 2 territories → capped to 60k deployed). The TurnController's periodic
            # reconciliation then synced strength_actual DOWN to the capped deployed
            # count every turn, causing the observed -60%/turn troop crash.
            # Remove the cap so deployed == strength_actual exactly.
            troops_per_territory = max(3000, faction.strength_actual // num_territories)

            for i, tid in enumerate(faction.territories):
                army_id = f"army_{fid}_{army_idx}"
                # Build unit composition
                units = {}
                remaining = troops_per_territory
                unit_types = sorted(comp.keys(), key=lambda ut: comp[ut], reverse=True)
                for j, ut in enumerate(unit_types):
                    if j == len(unit_types) - 1:
                        units[ut] = remaining
                        remaining = 0  # All remaining troops assigned to last unit type
                    else:
                        n = int(troops_per_territory * comp[ut])
                        units[ut] = max(0, n)
                        remaining -= n
                # Ensure no negative remaining
                if remaining > 0:
                    units[unit_types[0]] = units.get(unit_types[0], 0) + remaining

                armies[army_id] = Army(
                    id=army_id,
                    faction_id=fid,
                    location=tid,
                    commander_id=faction.ruler_id if i == 0 else "",
                    units=units,
                    morale=base_morale,
                    training=training,
                    supply=30,
                )
                army_idx += 1
        return armies

    # ── utility ─────────────────────────────────────────────────────────

    def format_year(self, year: int) -> str:
        """Render year with BC/AD support.

        - positive year_direction: '公元{year}年'
        - negative year_direction: '公元前{abs(year)}年'
        """
        if self.year_direction == "negative":
            return f"公元前{abs(year)}年"
        return f"公元{year}年"

    def get_timeline_events(self, year: int, season: str) -> list[dict]:
        """Return historical events matching the given year and season.

        Loads knowledge/timeline.json and filters by year+season.
        Returns an empty list if the file doesn't exist or has no match.

        Supports both formats:
        1. Array format (rome-triumvirate): {"year": -43, "season": "spring", ...}
        2. Object format (three-kingdoms): {"events": [{"year": 207, "month": 12, ...}]}
        """
        timeline_path = self._dir / "knowledge" / "timeline.json"
        if not timeline_path.is_file():
            return []

        with open(timeline_path, encoding="utf-8") as f:
            data = json.load(f)

        events: list[dict] = []
        if isinstance(data, list):
            events = data
        elif isinstance(data, dict):
            events = data.get("events", [])

        # Normalise season to lowercase English
        _SEASON_CN = {"春": "spring", "夏": "summer", "秋": "autumn", "冬": "winter"}
        season_lower = _SEASON_CN.get(season, season.lower())

        # Month → season mapping for three-kingdoms format
        _MONTH_TO_SEASON = {
            3: "spring",
            4: "spring",
            5: "spring",
            6: "summer",
            7: "summer",
            8: "summer",
            9: "autumn",
            10: "autumn",
            11: "autumn",
            12: "winter",
            1: "winter",
            2: "winter",
        }

        matches = []
        for e in events:
            if e.get("year") != year:
                continue
            # Format 1: explicit season field
            if "season" in e:
                ev_season = str(e["season"]).lower()
                if ev_season == season_lower:
                    matches.append(e)
            # Format 2: month field
            elif "month" in e:
                month = int(e["month"])
                if _MONTH_TO_SEASON.get(month) == season_lower:
                    matches.append(e)
            # Format 3: no season or month → match any
            else:
                matches.append(e)

        return matches

    @staticmethod
    def list_scenarios(root: Path | None = None) -> list[str]:
        """List all available scenario IDs (directories containing scenario.toml
        or knowledge/ data)."""
        if root is None:
            root = _find_scenarios_root()
        scenarios: list[str] = []
        if not root.is_dir():
            return scenarios
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            # A valid scenario has either scenario.toml or a knowledge/ subdirectory
            if (entry / "scenario.toml").is_file() or (entry / "knowledge").is_dir():
                scenarios.append(entry.name)
        return scenarios


# ─── character builder ──────────────────────────────────────────────────────


def _character_from_dict(cd: dict) -> Character:
    """Build a Character from a JSON dict.

    Supports both TK field names (stats.leadership, faction, location, loyalty)
    and rome-triumvirate field names (martial, intellect, politics, charisma, faction, role).
    """
    # Stats: TK uses nested stats dict, Caesar uses top-level attributes
    if "stats" in cd:
        stats = cd["stats"]
        leadership = stats.get("leadership", 50)
        might = stats.get("might", 50)
        intelligence = stats.get("intelligence", 50)
        politics_stat = stats.get("politics", 50)
        charisma = stats.get("charisma", 50)
    else:
        # Caesar format: martial, intellect, politics, charisma
        leadership = cd.get("leadership", cd.get("martial", 50))
        might = cd.get("might", cd.get("martial", 50))
        intelligence = cd.get("intelligence", cd.get("intellect", 50))
        politics_stat = cd.get("politics", cd.get("politics", 50))
        charisma = cd.get("charisma", 50)

    # Role detection
    role = cd.get("role", "")
    is_governor = role == "governor"
    is_commanding = role in ("general", "commander", "ruler")

    return Character(
        id=cd["id"],
        name=cd.get("name_cn", cd.get("name", cd["id"])),
        alias=cd.get("alias", cd.get("style", "")),
        leadership=leadership,
        might=might,
        intelligence=intelligence,
        politics=politics_stat,
        charisma=charisma,
        skills=cd.get("skills", cd.get("traits", [])),
        sworn_brothers=cd.get("sworn_brothers", []),
        spouse=cd.get("spouse", ""),
        mentor=cd.get("mentor", ""),
        faction_id=cd.get("faction", ""),
        location=cd.get("location", ""),
        loyalty=cd.get("loyalty", 80),
        birth=cd.get("birth", 150),
        death=cd.get("death", 200),
        is_governor=is_governor,
        is_commanding=is_commanding,
    )


def _parse_season(season_str: str) -> Season:
    """Parse a season string to a Season enum value."""
    season_map = {
        "spring": Season.SPRING,
        "summer": Season.SUMMER,
        "autumn": Season.AUTUMN,
        "winter": Season.WINTER,
    }
    return season_map.get(season_str.lower(), Season.WINTER)
