"""
Turn Controller — orchestrates the 10-step turn sequence.

Coordinates all engines to process one complete game turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..world import (
    Army,
    BattleResult,
    Command,
    Season,
    TurnResult,
    UnitType,
    WorldState,
)

if TYPE_CHECKING:
    from ..ai import DecisionEngine
    from ..ai.npc_planner import NPCPlanner
    from ..character import CharacterEngine
    from ..domestic import DomesticEngine
    from ..map import MapEngine
    from ..military import MilitaryEngine


class TurnController:
    """Orchestrates full turn execution across all engines."""

    def __init__(
        self,
        map_engine: MapEngine,
        char_engine: CharacterEngine,
        domestic_engine: DomesticEngine,
        military_engine: MilitaryEngine,
        decision_engine: DecisionEngine,
        npc_planner: NPCPlanner | None = None,
    ):
        self.map_engine = map_engine
        self.char_engine = char_engine
        self.domestic_engine = domestic_engine
        self.military_engine = military_engine
        self.decision_engine = decision_engine
        self.npc_planner = npc_planner

    def execute_turn(
        self,
        world_state: WorldState,
        player_commands: list[Command] | None = None,
        year: int = 207,
        turn_number: int = 1,
        player_decision: str = "",
    ) -> TurnResult:
        """
        Execute a full turn sequence.

        1. Climate roll
        2. Resource production
        3. Collect commands (player + NPC)
        4. Command validation
        5. Move resolution
        6. Battle resolution
        7. Domestic execution (recruit/develop)
        8. Character updates (death + loyalty)
        9. State persistence (skip)
        10. Return TurnResult
        """
        season = world_state.season

        # ── Normalize commands: dict → Command objects ──
        if player_commands:
            player_commands = [Command(**c) if isinstance(c, dict) else c for c in player_commands]

        # ── Step 1: Climate roll ──
        climate_events = self.domestic_engine.climate.roll_all(
            world_state.territories, season, year, turn_number
        )

        # ── Step 2: Resource production ──
        # Calculate troop counts per territory
        territory_troops = dict.fromkeys(world_state.territories, 0)
        for army in world_state.armies.values():
            if army.location in territory_troops:
                territory_troops[army.location] += army.total_troops

        # Build tax_rates and tech_levels from factions
        tax_rates = {fid: f.tax_rate for fid, f in world_state.factions.items() if f.is_active}
        tech_levels = {fid: f.tech_levels for fid, f in world_state.factions.items() if f.is_active}

        territory_results = self.domestic_engine.process_season(
            world_state.territories,
            season,
            year,
            turn_number,
            char_engine=self.char_engine,
            tax_rates=tax_rates,
            tech_levels=tech_levels,
            territory_troops=territory_troops,
        )

        # Apply season results: update faction treasuries and food
        resource_changes: dict[str, dict] = {}
        for tr in territory_results:
            territory = world_state.territories.get(tr.territory_id)
            if not territory or not territory.owner_id:
                continue
            fid = territory.owner_id
            faction = world_state.factions.get(fid)
            if not faction:
                continue
            faction.food += tr.food_delta
            faction.treasury += tr.tax_revenue
            faction.morale_actual = max(0, min(100, faction.morale_actual + tr.morale_change))

            if fid not in resource_changes:
                resource_changes[fid] = {"food_delta": 0, "tax_revenue": 0}
            resource_changes[fid]["food_delta"] += tr.food_delta
            resource_changes[fid]["tax_revenue"] += tr.tax_revenue

        # Check for famine across all active factions
        for fid, faction in world_state.factions.items():
            if not faction.is_active:
                continue
            if faction.food <= 0:
                if faction.food < 0:
                    faction.food = 0

                # Starvation attrition: troops desert or die when food runs out.
                # Each quarter at food=0: lose 15% of deployed troops.
                deployed = sum(
                    a.total_troops for a in world_state.armies.values()
                    if a.faction_id == fid
                )
                if deployed > 0:
                    starve_loss = max(200, int(deployed * 0.15))
                    # Apply to armies proportionally
                    for a in world_state.armies.values():
                        if a.faction_id == fid and a.total_troops > 0:
                            for unit_type in list(a.units.keys()):
                                if a.units[unit_type] > 0:
                                    loss = max(1, int(a.units[unit_type] * 0.15))
                                    a.units[unit_type] = max(0, a.units[unit_type] - loss)
                    faction.strength_actual = max(0, faction.strength_actual - starve_loss)

                # Famine effects
                faction.morale_actual = max(0, faction.morale_actual - 8)
                faction.legitimacy = max(0, faction.legitimacy - 12)
                # Population in all territories of this faction drops by 5%
                for tid in list(faction.territories):
                    t = world_state.territories.get(tid)
                    if t:
                        pop_loss = int(t.population * 0.05)
                        t.population = max(100, t.population - pop_loss)
                # Log famine in resource changes
                if fid not in resource_changes:
                    resource_changes[fid] = {"food_delta": 0, "tax_revenue": 0}
                resource_changes[fid]["famine_occurred"] = True

        # ── Landless faction upkeep ──
        # Factions with troops but no territories still consume food.
        # Each 100 troops consume 1 food per quarter (base maintenance).
        for fid, faction in world_state.factions.items():
            if not faction.is_active:
                continue
            if getattr(faction, "territories", None) and len(faction.territories) > 0:
                continue  # Already processed via territory_results above
            troops = getattr(faction, "strength_actual", 0)
            if troops <= 0:
                continue
            upkeep = max(1, troops // 100)  # At least 1 food for any troop presence
            faction.food = max(0, faction.food - upkeep)
            if fid not in resource_changes:
                resource_changes[fid] = {"food_delta": 0, "tax_revenue": 0}
            resource_changes[fid]["food_delta"] -= upkeep

        # ── Step 3: Collect commands ──
        # H36q: NPC commands come from LLM structured decisions (via
        # quarterly_resolver), NOT from TurnController's hard-coded
        # decision_engine. TurnController's role is purely economic baseline:
        # food, tax, population — not NPC strategy.
        # The old decision_engine.generate_commands() ran IN PARALLEL with
        # LLM NPC decisions, creating conflicting "second command system"
        # that overrode NPC strategy.
        all_commands: list[Command] = list(player_commands or [])

        # ── Step 4: Command validation ──
        valid_commands = self._validate_commands(all_commands, world_state)

        # ── Common enemy alliances ──
        # H36q REMOVED: This hard-coded rule redirected attacks between
        # allied factions to common enemies, overriding NPC LLM strategic
        # decisions. NPC strategy now comes from structured LLM commands.

        # Separate commands by type
        move_commands = [c for c in valid_commands if c.type in ("move", "attack", "defend")]
        # H36q: NPC recruit commands now flow through from LLM structured decisions.
        # The old block that filtered NPC recruit is removed — NPC recruitment
        # is handled by _apply_npc_structured_recruitment() in quarterly_resolver.
        domestic_commands = [c for c in valid_commands if c.type in ("recruit", "develop", "tax", "trade", "negotiate")]

        # ── Step 4.5: Alliance Processing ──
        # Negotiate commands form/break alliances; alliance state grants bonuses
        alliance_events: list[dict] = self._process_alliances(valid_commands, world_state)

        # ── Step 5: Move resolution ──
        move_results = []
        for cmd in move_commands:
            result = self._execute_move(cmd, world_state)
            if result:
                move_results.append(result)

        # ── Step 6: Battle resolution ──
        battles = self._resolve_all_battles(world_state)

        # ── Step 7: Domestic execution ──
        for cmd in domestic_commands:
            self._execute_domestic(cmd, world_state, resource_changes)

        # ── Step 8: Character updates ──
        character_events: list[dict] = []

        # Annual loyalty changes (applied in Winter)
        if season == Season.WINTER:
            from histrategy_engine.character.loyalty import calculate_loyalty_change

            for char in world_state.characters.values():
                if char.alive and char.faction_id:
                    faction = world_state.factions.get(char.faction_id)
                    if faction:
                        delta = calculate_loyalty_change(faction.legitimacy, char.politics)
                        if delta != 0:
                            char.loyalty = max(0, min(100, char.loyalty + delta))
                            character_events.append(
                                {
                                    "type": "loyalty_change",
                                    "character_id": char.id,
                                    "character_name": char.name,
                                    "delta": delta,
                                    "new_loyalty": char.loyalty,
                                    "reason": f"势力合法性影响(当前合法性: {faction.legitimacy})",
                                }
                            )

        for char_id in list(world_state.characters.keys()):
            char = world_state.characters[char_id]
            if not char.alive:
                continue

            # Natural death check — DISABLED (H37b: 人物永生铁律)
            # Characters are immortal in this game. Historical death years
            # (史可法/李自成 died 1645, the nanming start year) must NOT trigger
            # in-game death — killing faction leaders/advisors breaks the game:
            # the deterministic death isn't reflected in faction leadership, and
            # the next turn's narrative re-uses the "dead" character.
            # The nanming (山河鼎革) scenario assumes all named characters stay alive.
            _immortal = getattr(world_state, "scenario", "") in ("nanming",)
            if not _immortal and self.char_engine.check_natural_death(char_id, year, world_state.player_deviation):
                impacts = self.char_engine.kill_character(char_id)
                character_events.append(
                    {
                        "type": "natural_death",
                        "character_id": char_id,
                        "character_name": char.name,
                        "year": year,
                    }
                )
                for impact in impacts:
                    character_events.append(
                        {
                            "type": "loyalty_impact",
                            **impact,
                        }
                    )

            # Loyalty check for discontented
            if char.faction_id:
                discontented = self.char_engine.get_discontented(char.faction_id)
                for dc in discontented:
                    if dc.id == char_id:
                        defections = self.char_engine.check_defections(char.faction_id)
                        for d in defections:
                            character_events.append(d)
                            # Actually apply defection: remove from faction and clear roles
                            defect_char = world_state.characters.get(d["character_id"])
                            if defect_char:
                                defect_char.faction_id = ""
                                defect_char.is_governor = False
                                defect_char.is_commanding = False
                                # Clear commander reference in armies
                                for army in world_state.armies.values():
                                    if army.commander_id == d["character_id"]:
                                        army.commander_id = ""

        # Update faction legitimacy based on events gathered during the turn
        from histrategy_engine.governance.legitimacy import LegitimacyState, update_legitimacy

        for fid, faction in world_state.factions.items():
            if not faction.is_active:
                continue

            events = []
            if faction.tax_rate >= 0.4:
                events.append("heavy_tax")

            for combat in battles:
                if (
                    combat.attacker_id == fid
                    and combat.result in (BattleResult.VICTORY, BattleResult.DECISIVE_VICTORY)
                    or combat.defender_id == fid
                    and combat.result in (BattleResult.DEFEAT, BattleResult.DECISIVE_DEFEAT)
                ):
                    events.append("win_battle")

            leg_state = LegitimacyState(current_score=faction.legitimacy)
            updated_state = update_legitimacy(leg_state, events)
            faction.legitimacy = updated_state.current_score

        # ── Step 9: State persistence (skip) ──

        # ── Periodic reconciliation: sync faction.strength_actual with deployed troops ──
        # Over multiple turns, recruitment/attrition/battles can cause drift between
        # the faction-level strength counter and actual army unit counts.
        # CRITICAL: Only sync when armies are actually deployed. Without this guard,
        # a new game's first quarter (or any turn with no armies) zeroes ALL faction
        # strength_actual to 0, which the post-resolve guardrail then clamps to -35%.
        for fid, faction in world_state.factions.items():
            if not faction.is_active:
                continue
            deployed = sum(
                a.total_troops for a in world_state.armies.values()
                if a.faction_id == fid
            )
            # H37d: log the reconciliation to trace the troop crash.
            _n_armies = sum(1 for a in world_state.armies.values() if a.faction_id == fid)
            import logging as _h37d_logging
            _h37d_logging.getLogger("histrategy.trooptrace").warning(
                "[TROOPTRACE][reconcile] %s strength_actual=%d deployed=%d armies=%d",
                fid, getattr(faction, "strength_actual", 0), deployed, _n_armies,
            )
            if deployed > 0:
                faction.strength_actual = deployed

        # ── Step 10: Return TurnResult ──
        # Build faction snapshots
        faction_snapshots = dict(world_state.factions.items())

        # Advance season
        self._advance_season(world_state)

        return TurnResult(
            year=year,
            season=season,
            turn_number=turn_number,
            climate_events=climate_events,
            resource_changes=resource_changes,
            battles=battles,
            diplomatic_events=[],
            character_events=character_events,
            history_events=[],
            faction_snapshots=faction_snapshots,
            player_decision=player_decision,
            player_commands=list(player_commands or []),
        )

    # ── Helpers ──

    def _process_alliances(self, commands: list[Command], world_state: WorldState) -> list[dict]:
        """Process negotiate commands to form/break alliances and apply alliance bonuses.

        When faction A sends negotiate to faction B:
        - If B has relations >= 0 with A → alliance forms (mutual allies)
        - If B has relations < 0 but > -30 and B.diplomacy > 0.6 → alliance forms
        - Otherwise, relations improve slightly (the proposal was heard)

        Alliance bonuses applied immediately:
        - Morale: +2 per active ally
        - Defense/Attack coordination: handled by existing common-enemy mechanic
        """
        events: list[dict] = []

        for cmd in commands:
            if cmd.type != "negotiate":
                continue

            source_id = cmd.faction_id
            target_id = cmd.params.get("target_faction", "")
            proposal = cmd.params.get("proposal", "")

            if not target_id or source_id == target_id:
                continue

            source = world_state.factions.get(source_id)
            target = world_state.factions.get(target_id)
            if not source or not target or not target.is_active:
                continue

            # Check action param (set by intent parser, not keyword matching)
            action = cmd.params.get("action", "form_alliance")
            is_break = action == "break_alliance"
            is_refuge = action == "seek_refuge"

            if is_break:
                # Remove from mutual allies
                if target_id in source.allies:
                    source.allies.remove(target_id)
                    events.append({
                        "type": "alliance_broken",
                        "source": source_id,
                        "target": target_id,
                        "reason": proposal or "单方面断交",
                    })
                if source_id in target.allies:
                    target.allies.remove(source_id)
                continue

            # ── seek_refuge: 流亡势力依附/投靠盟友，请求割让一座非首都城作为新基地 ──
            if is_refuge:
                rel = target.relations.get(source_id, 0)
                will_host = bool(
                    source_id in target.allies
                    or target_id in source.allies
                    or rel >= 0
                )
                if not will_host:
                    # 拒绝收留：关系略微改善（请求被听到了）
                    target.relations[source_id] = max(-100, rel + 5)
                    events.append({
                        "type": "refuge_rejected",
                        "source": source_id,
                        "target": target_id,
                        "proposal": proposal,
                    })
                    continue

                # 目标势力同意：割让一座非首都城给流亡方作为新基地。
                cede_city = None
                for tid in list(target.territories):
                    if tid != getattr(target, "capital", ""):
                        cede_city = tid
                        break
                if cede_city:
                    territory = world_state.territories.get(cede_city)
                    if territory:
                        territory.owner_id = source_id
                    if cede_city in target.territories:
                        target.territories.remove(cede_city)
                    if cede_city not in source.territories:
                        source.territories.append(cede_city)
                    # 迁都到新基地（流亡方原先的都城已丢失或不存在）
                    source.capital = cede_city
                    # 流亡军迁驻新城
                    for a in world_state.armies.values():
                        if a.faction_id == source_id and not a.location:
                            a.location = cede_city
                            break
                    # 结盟 + 关系提升
                    if target_id not in source.allies:
                        source.allies.append(target_id)
                    if source_id not in target.allies:
                        target.allies.append(source_id)
                    target.relations[source_id] = min(100, rel + 25)
                    source.relations[target_id] = min(100, source.relations.get(target_id, 0) + 25)
                    events.append({
                        "type": "refuge_granted",
                        "source": source_id,
                        "target": target_id,
                        "territory": cede_city,
                        "proposal": proposal,
                    })
                else:
                    # 目标无城可割（仅剩首都）→ 关系改善，未获基地
                    target.relations[source_id] = min(100, rel + 10)
                    events.append({
                        "type": "refuge_pending",
                        "source": source_id,
                        "target": target_id,
                        "proposal": proposal,
                    })
                continue

            # Alliance formation: check if target would accept
            rel = target.relations.get(source_id, 0)
            will_accept = bool(
                rel >= 0
                or (rel > -30 and getattr(target, "diplomacy", 0.5) > 0.6)
            )

            if will_accept:
                # Form mutual alliance
                if target_id not in source.allies:
                    source.allies.append(target_id)
                if source_id not in target.allies:
                    target.allies.append(source_id)
                # Boost relations
                target.relations[source_id] = min(100, rel + 20)
                source.relations[target_id] = min(100, source.relations.get(target_id, 0) + 20)
                events.append({
                    "type": "alliance_formed",
                    "source": source_id,
                    "target": target_id,
                    "proposal": proposal,
                })
            else:
                # Proposal heard but rejected — slight relations improvement
                target.relations[source_id] = max(-100, rel + 5)
                events.append({
                    "type": "alliance_rejected",
                    "source": source_id,
                    "target": target_id,
                    "proposal": proposal,
                    "relations_after": target.relations[source_id],
                })

        # ── Apply alliance morale bonus ──
        for fid, faction in world_state.factions.items():
            if not faction.is_active:
                continue
            ally_count = len([a for a in faction.allies if a in world_state.factions and world_state.factions[a].is_active])
            if ally_count > 0:
                morale_bonus = min(6, ally_count * 2)  # cap at +6
                faction.morale_actual = min(100, faction.morale_actual + morale_bonus)

        return events

    def _validate_commands(self, commands: list[Command], world_state: WorldState) -> list[Command]:
        valid: list[Command] = []
        for cmd in commands:
            if self._is_valid_command(cmd, world_state):
                valid.append(cmd)
        return valid

    def _is_valid_command(self, cmd: Command, world_state: WorldState) -> bool:
        # Handle both Command objects and dicts
        fid = getattr(cmd, "faction_id", None) or (
            cmd.get("faction_id") if isinstance(cmd, dict) else None
        )
        if not fid:
            return False

        faction = world_state.factions.get(fid)
        if not faction or not faction.is_active:
            return False

        cmd_type = getattr(cmd, "type", None) or (
            cmd.get("type") if isinstance(cmd, dict) else None
        )
        params = getattr(cmd, "params", None) or (
            cmd.get("params", {}) if isinstance(cmd, dict) else {}
        )

        if cmd_type == "develop":
            tid = (
                params.get("territory", "")
                if isinstance(params, dict)
                else getattr(params, "territory", "")
            )
            territory = world_state.territories.get(tid)
            if not territory:
                return False
            return territory.owner_id == fid

        if cmd_type == "recruit":
            # 流亡军（0 领地）：允许征兵，从跟随百姓征召，不要求拥有领地。
            if not faction.territories:
                return True
            tid = (
                params.get("territory", "")
                if isinstance(params, dict)
                else getattr(params, "territory", "")
            )
            territory = world_state.territories.get(tid)
            if not territory:
                return False
            return territory.owner_id == fid

        if cmd_type in ("move", "attack", "defend"):
            target = (
                params.get("destination")
                or params.get("target_territory")
                or params.get("territory", "")
            )
            if not target or target not in world_state.territories:
                return False
            # ── Skip attacks on own territories ──
            # NPC LLM may hallucinate commands to attack already-owned territory
            # (e.g. Qing attacking Kaifeng when Kaifeng is already under Qing control).
            if cmd_type == "attack":
                territory = world_state.territories.get(target)
                if territory and territory.owner_id == fid:
                    return False
            return True

        if cmd_type == "tax":
            rate = params.get("rate")
            return not (rate is None or not 0.1 <= rate <= 0.5)

        # H38b: Accept policy/economic/diplomacy commands — these are handled
        # by MacroPolicyEngine, not the deterministic baseline.
        if cmd_type in ("train", "fortify", "reward", "disarm", "reform", "relief",
                        "patrol", "negotiate", "trade", "spy", "research",
                        "appoint", "dismiss", "rest", "aid_request"):
            return True

        return False

    def _execute_move(self, cmd: Command, world_state: WorldState) -> dict | None:
        faction_id = cmd.faction_id
        target = (
            cmd.params.get("destination")
            or cmd.params.get("target_territory")
            or cmd.params.get("territory", "")
        )

        # For defend: check if already have army at target → no-op
        if cmd.type == "defend":
            existing = self._find_faction_army_at(faction_id, target, world_state)
            if existing:
                return {
                    "command_type": "defend",
                    "faction_id": faction_id,
                    "army_id": existing.id,
                    "location": target,
                    "success": True,
                    "reason": "已有驻军防守",
                }

        # Find an army belonging to this faction
        army = self._find_faction_army(faction_id, world_state, prefer_border=True)
        if not army:
            return None

        # 流亡军（无驻地 location=""）：直接抵达目标 —— 流浪军队无固定基地，
        # 沿途机动开赴目的地。
        if not army.location:
            army.location = target
            return {
                "command_type": cmd.type,
                "faction_id": faction_id,
                "army_id": army.id,
                "from": "",
                "to": target,
                "success": True,
                "reason": "流亡军开赴目标",
            }

        result = self.military_engine.move_army(army, target, self.map_engine)
        return {
            "command_type": cmd.type,
            "faction_id": faction_id,
            "army_id": army.id,
            "from": result.from_location,
            "to": result.to_location,
            "success": result.success,
            "reason": result.reason,
        }

    def _execute_domestic(
        self, cmd: Command, world_state: WorldState, resource_changes: dict
    ) -> None:
        faction_id = cmd.faction_id
        faction = world_state.factions.get(faction_id)
        if not faction:
            return

        if cmd.type == "recruit":
            tid = cmd.params.get("territory", "")
            unit_type_str = cmd.params.get("unit_type", "infantry")
            amount = cmd.params.get("amount", 500)

            try:
                unit_type = UnitType(unit_type_str)
            except ValueError:
                return

            # 流亡军：0 领地，直接从跟随百姓征召（不减 territory 人口，只耗金库）。
            if not faction.territories:
                pop_source = getattr(faction, "population", 0) or 0
                if pop_source <= 0:
                    pop_source = max(1, int(getattr(faction, "strength_actual", 0) or 0) * 2)
                max_recruit = max(1, int(pop_source * 0.05))
                amount = min(int(amount), max_recruit)
                cost = amount * 3
                if faction.treasury < cost:
                    amount = int(faction.treasury // 3)
                    cost = amount * 3
                if amount <= 0:
                    return
                faction.treasury -= cost
                faction.strength_actual += amount
                army = self._find_faction_army(faction_id, world_state)
                if army:
                    army.units[unit_type] = army.units.get(unit_type, 0) + amount
                if faction_id not in resource_changes:
                    resource_changes[faction_id] = {"food_delta": 0, "tax_revenue": 0}
                resource_changes[faction_id]["treasury_spent"] = (
                    resource_changes[faction_id].get("treasury_spent", 0) + cost
                )
                return

            territory = world_state.territories.get(tid)
            if not territory:
                return

            rec_result = self.military_engine.recruit(
                territory, unit_type, amount, faction.treasury, territory.population
            )

            if rec_result.success:
                faction.treasury -= rec_result.cost
                territory.population -= amount

                # Add to an army in this territory
                army = self._find_or_create_army(faction_id, tid, world_state)
                army.units[unit_type] = army.units.get(unit_type, 0) + amount
                faction.strength_actual += amount

                if faction_id not in resource_changes:
                    resource_changes[faction_id] = {"food_delta": 0, "tax_revenue": 0}
                resource_changes[faction_id]["treasury_spent"] = (
                    resource_changes[faction_id].get("treasury_spent", 0) + rec_result.cost
                )

        elif cmd.type == "develop":
            tid = cmd.params.get("territory", "")
            territory = world_state.territories.get(tid)
            if not territory or territory.owner_id != faction_id:
                return

            # Calculate development cost
            current_dev = territory.development
            target_dev = min(100, current_dev + 5)
            cost = self.domestic_engine.calculate_development_cost(territory, target_dev)

            if faction.treasury >= cost:
                faction.treasury -= cost
                territory.development = target_dev
                if faction_id not in resource_changes:
                    resource_changes[faction_id] = {"food_delta": 0, "tax_revenue": 0}
                resource_changes[faction_id]["treasury_spent"] = (
                    resource_changes[faction_id].get("treasury_spent", 0) + cost
                )

        elif cmd.type == "tax":
            rate = cmd.params.get("rate", 0.3)
            faction.tax_rate = max(0.1, min(0.5, rate))

        # H38b: New domestic command handlers — deterministic portion only.
        # Full effects (diplomacy/reform consequences) are handled by MacroPolicyEngine.
        elif cmd.type == "reward":
            amount = cmd.params.get("amount", 1000)
            if faction.treasury >= amount:
                faction.treasury -= amount
                faction.morale_actual = min(100, getattr(faction, "morale_actual", 50) + 5)
                if faction_id not in resource_changes:
                    resource_changes[faction_id] = {"food_delta": 0, "tax_revenue": 0}
                resource_changes[faction_id]["treasury_spent"] = (
                    resource_changes[faction_id].get("treasury_spent", 0) + amount
                )
        elif cmd.type == "train":
            faction.morale_actual = min(100, getattr(faction, "morale_actual", 50) + 3)
        elif cmd.type == "fortify":
            tid = cmd.params.get("territory", "")
            territory = world_state.territories.get(tid) if tid else None
            if territory and territory.owner_id == faction_id:
                territory.development = min(100, getattr(territory, "development", 10) + 5)
        elif cmd.type == "reform":
            # Reforms reduce treasury short-term but boost morale/population
            cost = 2000
            if faction.treasury >= cost:
                faction.treasury -= cost
                faction.morale_actual = min(100, getattr(faction, "morale_actual", 50) + 2)
                if faction_id not in resource_changes:
                    resource_changes[faction_id] = {"food_delta": 0, "tax_revenue": 0}
                resource_changes[faction_id]["treasury_spent"] = (
                    resource_changes[faction_id].get("treasury_spent", 0) + cost
                )
        elif cmd.type == "relief":
            # Relief: food -2000, morale +3
            cost_food = 2000
            if faction.food >= cost_food:
                faction.food -= cost_food
                faction.morale_actual = min(100, getattr(faction, "morale_actual", 50) + 3)

    def _resolve_all_battles(self, world_state: WorldState) -> list:
        """Find all territories with armies from different factions and resolve battles."""
        battles = []

        # Group armies by location
        location_armies: dict[str, list[Army]] = {}
        for army in world_state.armies.values():
            if army.total_troops <= 0:
                continue
            location_armies.setdefault(army.location, []).append(army)

        for location, armies in location_armies.items():
            # Only resolve if multiple factions present
            faction_ids = {a.faction_id for a in armies}
            if len(faction_ids) < 2:
                continue

            # Resolve battles pairwise between hostile factions
            resolved_pairs: set[tuple[str, str]] = set()

            for i, army_a in enumerate(armies):
                for army_b in armies[i + 1 :]:
                    if army_a.faction_id == army_b.faction_id:
                        continue
                    pair = tuple(sorted([army_a.faction_id, army_b.faction_id]))
                    if pair in resolved_pairs:
                        continue
                    resolved_pairs.add(pair)

                    # Determine who is attacker and defender based on territory ownership
                    territory = world_state.territories.get(location)
                    if territory and territory.owner_id == army_b.faction_id:
                        attacker = army_a
                        defender = army_b
                    elif territory and territory.owner_id == army_a.faction_id:
                        attacker = army_b
                        defender = army_a
                    else:
                        # Fallback if neutral/unowned
                        attacker = army_a
                        defender = army_b

                    combat = self.military_engine.resolve_battle(
                        attacker,
                        defender,
                        location,
                        self.map_engine,
                        self.char_engine,
                    )
                    battles.append(combat)

                    # ── Sync faction.strength_actual with actual army totals ──
                    # Previously strength_actual only increased (via recruit) but never
                    # decreased when troops died in battle — causing infinite phantom manpower.
                    for _army, _casualties in [(attacker, combat.attacker_casualties),
                                                (defender, combat.defender_casualties)]:
                        fid = _army.faction_id
                        _f = world_state.factions.get(fid)
                        if _f:
                            total_lost = sum(_casualties.values())
                            _f.strength_actual = max(0, _f.strength_actual - total_lost)

                    # If territory captured, change ownership to attacker
                    if combat.territory_captured:
                        territory = world_state.territories.get(location)
                        if territory:
                            old_owner = territory.owner_id
                            territory.owner_id = attacker.faction_id

                            # Update faction territories
                            if old_owner and old_owner in world_state.factions:
                                old_faction = world_state.factions[old_owner]
                                if location in old_faction.territories:
                                    old_faction.territories.remove(location)
                            if attacker.faction_id in world_state.factions:
                                atk_faction = world_state.factions[attacker.faction_id]
                                if location not in atk_faction.territories:
                                    atk_faction.territories.append(location)

                                # ── Defection mechanic: decisive victories can trigger
                                # nearby territories to surrender (historical: Qing bribery
                                # of Ming generals like Wu Sangui, Liu Liangzuo) ──
                                if combat.result == BattleResult.DECISIVE_VICTORY:
                                    atk_aggression = getattr(atk_faction, "aggression", 0.5)
                                    import random as _random
                                    if atk_aggression > 0.6 and _random.random() < 0.25:
                                        # Find a neighboring territory owned by the defender
                                        # that is weakly defended
                                        for neighbor_id in self.map_engine.get_neighbors(location):
                                            nt = world_state.territories.get(neighbor_id)
                                            if nt and nt.owner_id == old_owner:
                                                # Check if this neighbor has no defending army
                                                has_garrison = any(
                                                    a.faction_id == old_owner and a.total_troops > 0
                                                    for a in world_state.armies.values()
                                                    if a.location == neighbor_id
                                                )
                                                if not has_garrison:
                                                    # Defection! Territory switches sides
                                                    nt.owner_id = attacker.faction_id
                                                    def_faction = world_state.factions.get(old_owner) if old_owner else None
                                                    if def_faction and neighbor_id in def_faction.territories:
                                                        def_faction.territories.remove(neighbor_id)
                                                    if neighbor_id not in atk_faction.territories:
                                                        atk_faction.territories.append(neighbor_id)
                                                    if def_faction:
                                                        def_faction.morale_actual = max(0, def_faction.morale_actual - 15)
                                                    atk_faction.morale_actual = min(100, atk_faction.morale_actual + 5)
                                                    break  # One defection per decisive victory

                                # ── Victory looting: capturing a territory yields food + morale ──
                                # Historical: armies looted captured cities. But defenders
                                # sometimes practiced "scorched earth" (坚壁清野).
                                def_faction = world_state.factions.get(old_owner) if old_owner else None
                                import random as _rl
                                if _rl.random() < 0.30:
                                    # Scorched earth: defender destroyed supplies before retreat
                                    loot_food = 0
                                else:
                                    loot_food = min(5000, int(def_faction.food * 0.15) + 2000) if def_faction else 2000
                                atk_faction.food += loot_food
                                # Conquest momentum: consecutive victories build morale
                                conquest_bonus = getattr(atk_faction, '_conquest_streak', 0)
                                atk_faction._conquest_streak = conquest_bonus + 1
                                morale_gain = min(3 + conquest_bonus, 10)
                                atk_faction.morale_actual = min(100, atk_faction.morale_actual + morale_gain)
                                if def_faction:
                                    def_faction.morale_actual = max(0, def_faction.morale_actual - 5)
                                    def_faction.food = max(0, def_faction.food - loot_food)
                                    def_faction._conquest_streak = 0  # Reset defender's streak
                                    # ── Morale collapse: extended demoralization triggers defection ──
                                    if def_faction.morale_actual <= 0:
                                        # Each morale=0 turn, 15% chance a random territory defects
                                        if _rl.random() < 0.15 and len(def_faction.territories) > 1:
                                            # Find a border territory without garrison
                                            for tid in list(def_faction.territories):
                                                if tid == location:
                                                    continue  # Not the one just captured
                                                has_garr = any(
                                                    a.faction_id == old_owner and a.total_troops > 0
                                                    for a in world_state.armies.values()
                                                    if a.location == tid
                                                )
                                                if not has_garr and _rl.random() < 0.5:
                                                    # Territory defects to attacker
                                                    t = world_state.territories.get(tid)
                                                    if t:
                                                        t.owner_id = attacker.faction_id
                                                        def_faction.territories.remove(tid)
                                                        atk_faction.territories.append(tid)
                                                        atk_faction.morale_actual = min(100, atk_faction.morale_actual + 3)
                                                    break

        return battles

    def _find_faction_army(
        self, faction_id: str, world_state: WorldState, prefer_border: bool = False
    ) -> Army | None:
        """Find an army belonging to a faction, optionally preferring border armies."""
        faction_armies = [
            a
            for a in world_state.armies.values()
            if a.faction_id == faction_id and a.total_troops > 0
        ]

        if not faction_armies:
            # 流亡军：无领地势力若仍有兵力，补建一支无驻地军队以便移动/进攻。
            faction = world_state.factions.get(faction_id)
            if (
                faction
                and getattr(faction, "is_active", True)
                and getattr(faction, "strength_actual", 0) > 0
            ):
                army_id = f"army_{faction_id}_exile"
                army = Army(
                    id=army_id,
                    faction_id=faction_id,
                    location="",
                    units={UnitType.INFANTRY: int(faction.strength_actual)},
                )
                world_state.armies[army_id] = army
                return army
            return None

        if prefer_border:
            borders = self.map_engine.get_border_territories(faction_id)
            border_armies = [a for a in faction_armies if a.location in borders]
            if border_armies:
                return border_armies[0]

        return faction_armies[0]

    def _find_faction_army_at(
        self, faction_id: str, territory_id: str, world_state: WorldState
    ) -> Army | None:
        """Find an army belonging to a faction at a specific territory (no creation)."""
        for army in world_state.armies.values():
            if (
                army.faction_id == faction_id
                and army.location == territory_id
                and army.total_troops > 0
            ):
                return army
        return None

    def _find_or_create_army(
        self, faction_id: str, territory_id: str, world_state: WorldState
    ) -> Army:
        """Find an existing army in the territory or create a new one."""
        for army in world_state.armies.values():
            if army.faction_id == faction_id and army.location == territory_id:
                return army

        army_id = f"army_{faction_id}_{territory_id}"
        army = Army(
            id=army_id,
            faction_id=faction_id,
            location=territory_id,
        )
        world_state.armies[army_id] = army
        return army

    def _advance_season(self, world_state: WorldState) -> None:
        """Advance to the next season."""
        seasons = [Season.SPRING, Season.SUMMER, Season.AUTUMN, Season.WINTER]
        idx = seasons.index(world_state.season)
        next_idx = (idx + 1) % 4
        world_state.season = seasons[next_idx]
        if next_idx == 0:
            world_state.year += 1
        world_state.turn_number += 1
