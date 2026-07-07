"""GameEngine turn processing mixin: process_turn and all variants."""
from __future__ import annotations

import contextlib
import os

from ..state.world_state import save_world
from .helpers import (
    FIRST_TURN_SUGGESTIONS,
    _auto_mobilize_for_attack,
    _build_faction_id_map,
    _build_territory_id_map,
    _inject_v3_into_baseline,
    _suppress_stderr,
    apply_event_effects,
)

# ── Shared helpers (deduplicated from methods below) ──────────

def _advance_season_and_year(ws) -> None:
    """Advance season and year in a WorldState.

    Was duplicated identically at L1053 and L1193.
    """
    from histrategy_engine.world import Season as _Season

    _seasons = list(_Season)
    try:
        _idx = _seasons.index(ws.season)
        ws.season = _seasons[(_idx + 1) % len(_seasons)]
        if ws.season == _seasons[0]:  # wrapped around → new year
            ws.year += 1
    except (ValueError, IndexError):
        pass


def _check_player_game_over(ws, player) -> dict | None:
    """Check for defeat (player dead) or victory (only player faction remains).

    Was duplicated at L154-171 and L596-609.
    """
    # Defeat: player faction is gone
    if not player or not player.is_active or getattr(player, "strength_actual", 0) <= 0:
        return {
            "type": "defeat",
            "message": "# 势力覆灭\n\n你的势力已经不复存在。\n乱世之中，成王败寇。\n\n感谢游玩《三國志略》。",
        }

    # Victory: player is the only active faction
    active_factions = [
        fid for fid, f in ws.factions.items()
        if f.is_active and getattr(f, "strength_actual", 0) > 0
    ]
    if len(active_factions) == 1 and active_factions[0] == ws.player_faction_id:
        return {
            "type": "victory",
            "message": "# 天下一统\n\n经过多年的征战，你终于平定了天下。\n海内归一，万民归心。\n\n你就是这个时代最伟大的君主！\n\n感谢游玩《三國志略》。",  # noqa: E501
        }

    return None


class TurnProcessorMixin:
    """Mixin providing turn processing methods for GameEngine."""

    def process_turn(self, player_decision: str) -> dict:
        """Process a player's decision and return results.

        v2: IntentParser → CommandValidator → TurnController.execute_turn() →
            NarrativeEngine.generate_turn_narrative()
        v1: WorldSimEngine.simulate()
        symmetric: GameRoom → DecisionBus → QuarterlyResolver (multi-faction)
        """
        if not self.game_started:
            return self._fallback_intro()

        # ── Symmetric multi-faction path (HISTRATEGY_SYMMETRIC=1) ──
        if os.environ.get("HISTRATEGY_SYMMETRIC") == "1":
            return self.process_turn_symmetric(player_decision)

        if self._use_v3:
            if self.world_simulator:
                return self._process_turn_v3(player_decision)
            if self._macro_sim:
                return self._process_turn_macro(player_decision)
        if self._use_v2:
            return self._process_turn_v2(player_decision)
        return self._process_turn_v1(player_decision)
    def _process_turn_v2(self, player_decision: str) -> dict:
        """v2 turn processing pipeline."""
        ws = self.world_state_v2
        current_year = ws.year
        current_season = ws.season

        # Step 1: Parse player intent into commands
        player_commands = []
        if self.intent_parser:
            player_commands = self.intent_parser.parse(player_decision, ws.player_faction_id)

        # Store for simulation history logging
        self._last_player_decision = player_decision
        self._last_player_commands = list(player_commands)

        # Step 2: Validate commands
        if self.command_validator:
            player_commands = self.command_validator.validate(player_commands, ws)

        # Step 3: Execute turn via TurnController
        turn_result = self.turn_controller.execute_turn(
            ws,
            player_commands=player_commands,
            year=ws.year,
            turn_number=ws.turn_number,
        )

        # Step 4: Check historical events
        proposals = []
        if self.history_engine:
            try:
                # Sync completed/averted events with history_engine
                for evt_id in ws.completed_events:
                    self.history_engine._triggered_events.add(evt_id)
                for evt_id in ws.averted_events:
                    if evt_id not in self.history_engine._averted_events:
                        self.history_engine._averted_events[evt_id] = "Restored from world state"
                    self.history_engine.block_downstream(evt_id)

                proposals = self.history_engine.check_events(
                    current_year, current_season, ws, deviation=ws.player_deviation
                )
                for prop in proposals:
                    apply_event_effects(ws, prop.effects.get("effects", {}))
                    turn_result.history_events.append(
                        {
                            "event_id": prop.event_id,
                            "title": prop.title,
                            "outcome": prop.effects.get("outcome", "default"),
                            "description": prop.effects.get("outcome_description", ""),
                            "effects": prop.effects.get("effects", {}),
                        }
                    )
            except Exception:
                pass

        # Step 5 & 6: Generate narrative and plan suggestions (Parallelized)
        narrative_text = ""
        new_choices = []

        # Snapshot cumulative LLM token counters before parallel calls
        _tok_snap = {"total": 0}
        if self.narrative_engine and self.narrative_engine.is_available:
            llm = getattr(self.narrative_engine, "llm", None)
            if llm and hasattr(llm, "total_all_tokens"):
                _tok_snap["total"] = llm.total_all_tokens

        averted_list = list(ws.averted_events)
        if self.history_engine:
            averted_list = list(set(averted_list) | self.history_engine._blocked_downstream)

        room_id = getattr(self, "_room_id", "default")

        if self.narrative_engine and self.narrative_engine.is_available:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                # Submit both tasks
                future_narrative = executor.submit(
                    self.narrative_engine.generate_turn_narrative,
                    turn_result,
                    deviation=ws.player_deviation,
                    averted_events=averted_list,
                    world_state=ws,
                    room_id=room_id,
                )
                future_suggestions = executor.submit(
                    self.narrative_engine.generate_plan_suggestions, ws, ws.player_faction_id
                )

                # Retrieve results with error fallback
                try:
                    with _suppress_stderr():
                        narrative_text = future_narrative.result(timeout=30)
                except Exception:
                    narrative_text = self._offline_v2_narrative(turn_result)

                try:
                    with _suppress_stderr():
                        new_choices = future_suggestions.result(timeout=30)
                except Exception:
                    new_choices = self._offline_v2_suggestions()
        else:
            narrative_text = self._offline_v2_narrative(turn_result)
            new_choices = self._offline_v2_suggestions()

        # Step 7: Build result dict
        player = ws.factions.get(ws.player_faction_id)
        game_over = _check_player_game_over(ws, player)

        # Extract state changes from resource_changes
        resource_changes = turn_result.resource_changes.get(ws.player_faction_id, {})

        # Track LLM token usage via cumulative counters (works across parallel calls)
        _usage = {
            "command_tokens": 0,  # Narrative + Suggestions (all LLM calls this turn)
            "plan_tokens": 0,  # Suggestions generation
            "npc_tokens": 0,  # NPC AI (not yet tracked separately)
            "sim_tokens": 0,  # Deterministic simulation (free)
        }
        if self.narrative_engine and self.narrative_engine.is_available:
            llm = getattr(self.narrative_engine, "llm", None)
            if llm and hasattr(llm, "total_all_tokens"):
                _usage["command_tokens"] = max(llm.total_all_tokens - _tok_snap.get("total", 0), 0)

        # Generate a concise aftermath from resource changes + key events
        aftermath_parts = []
        is_en = getattr(self, "_scenario_language", "zh") == "en"
        if resource_changes.get("food_delta", 0) != 0:
            sign = "+" if resource_changes["food_delta"] > 0 else ""
            label = "Food" if is_en else "粮草"
            aftermath_parts.append(f"{label}{sign}{resource_changes['food_delta']}")
        if resource_changes.get("tax_revenue", 0) != 0:
            sign = "+" if resource_changes["tax_revenue"] > 0 else ""
            label = "Gold" if is_en else "资金"
            aftermath_parts.append(f"{label}{sign}{resource_changes['tax_revenue']}")
        if resource_changes.get("strength_delta", 0) != 0:
            sign = "+" if resource_changes["strength_delta"] > 0 else ""
            label = "Troops" if is_en else "兵力"
            aftermath_parts.append(f"{label}{sign}{resource_changes['strength_delta']}")
        if resource_changes.get("morale_delta", 0) != 0:
            sign = "+" if resource_changes["morale_delta"] > 0 else ""
            label = "Morale" if is_en else "民心"
            aftermath_parts.append(f"{label}{sign}{resource_changes['morale_delta']}")

        # Extract the last 2-3 sentences of narrative as summary
        if narrative_text:
            import re as _re

            sentences = _re.split(r"[。！？]", narrative_text)
            sentences = [s.strip() for s in sentences if s.strip()]
            summary_sentences = sentences[-2:] if len(sentences) > 2 else sentences[-1:]
            aftermath_text = "。".join(summary_sentences) + "。"
        else:
            aftermath_text = "The realm is calm, all is under control.\n" if is_en else "局势已定，天下大势尽在掌握。\n"

        if aftermath_parts:
            prefix = "This turn: " if is_en else "本回合："
            sep = ", " if is_en else "，"
            suffix = ". " if is_en else "。"
            aftermath_text = prefix + sep.join(aftermath_parts) + suffix + "\n\n" + aftermath_text

        result = {
            "narrative": narrative_text,
            "aftermath": aftermath_text,
            "bureaucracy": [
                {"department": "军机处", "official": "参军", "action": f"执行{len(player_commands)}项军令"}
            ],
            "state_changes": {
                "food": resource_changes.get("food_delta", 0),
                "treasury": resource_changes.get("tax_revenue", 0),
            },
            "_usage": _usage,
            "seeds": [
                {"title": evt["title"], "description": evt.get("description", "")[:80]}
                for evt in self.history_engine.all_events
                if evt["id"] not in self.history_engine._triggered_events
                and evt["id"] not in self.history_engine.averted_events
                and evt["id"] not in self.history_engine._blocked_downstream
                and abs(evt["year"] - ws.year) <= 1
            ]
            if self.history_engine
            else [],
            "npc_reactions": [],
            "npc_actions": [],
            "events_occurred": turn_result.character_events,
            "new_choices": new_choices,
            "game_over": game_over,
            "world_state": ws,
        }

        # Score the turn for deviation
        if player and self.history_engine:
            try:
                if ws.player_deviation > 0.0:
                    if is_en:
                        result["aftermath"] = (
                            f"[Historian's Note: Historical Deviation {ws.player_deviation:.2f}]\n\n"
                            + result["aftermath"]
                        )
                    else:
                        result["aftermath"] = (
                            f"【史官注：历史偏离度 {ws.player_deviation:.2f}】\n\n" + result["aftermath"]
                        )
            except Exception:
                pass

        # Save state
        self._save_v2()

        # Log turn
        try:
            from ..engine.log_exporter import append_to_session_log

            append_to_session_log(
                ws.turn_number,
                ws.year,
                ws.season.value,
                player_decision,
                result,
            )
        except Exception:
            pass

        self._log_simulation_history()

        return result
    def _process_turn_v3(self, player_decision: str) -> dict:
        """v3 turn processing pipeline — LLM-driven simulation with guardrails.

        1. Parse intent (same as v2)
        2. Execute deterministic baseline (same as v2)
        3. LLM WorldSimulator generates nonlinear delta
        4. GuardrailValidator checks delta
        5. StateApplier applies validated delta
        6. NarrativeEngine generates story with full context
        """
        ws = self.world_state_v2
        current_year = ws.year
        current_season = ws.season

        # Step 1: Parse player intent (same as v2)
        player_commands = []
        if self.intent_parser:
            player_commands = self.intent_parser.parse(player_decision, ws.player_faction_id)
        self._last_player_decision = player_decision
        self._last_player_commands = list(player_commands)

        # Step 2: Validate commands (same as v2)
        if self.command_validator:
            player_commands = self.command_validator.validate(player_commands, ws)

        # ── v3: Auto-mobilize ──────────────────────────────────
        # When player says "attack with 60K from wancheng" but only 5K
        # army exists, auto-transfer faction reserves to the army.
        _auto_mobilize_for_attack(player_commands, ws)

        # Step 3: Execute deterministic baseline (same as v2 — TurnController)
        baseline_result = self.turn_controller.execute_turn(
            ws,
            player_commands=player_commands,
            year=ws.year,
            turn_number=ws.turn_number,
        )

        # Step 4: History events (same as v2)
        proposals = []
        if self.history_engine:
            try:
                for evt_id in ws.completed_events:
                    self.history_engine._triggered_events.add(evt_id)
                for evt_id in ws.averted_events:
                    if evt_id not in self.history_engine._averted_events:
                        self.history_engine._averted_events[evt_id] = "Restored"
                    self.history_engine.block_downstream(evt_id)
                proposals = self.history_engine.check_events(
                    current_year, current_season, ws, deviation=ws.player_deviation
                )
                for prop in proposals:
                    apply_event_effects(ws, prop.effects.get("effects", {}))
                    baseline_result.history_events.append(
                        {
                            "event_id": prop.event_id,
                            "title": prop.title,
                            "outcome": prop.effects.get("outcome", "default"),
                            "description": prop.effects.get("outcome_description", ""),
                            "effects": prop.effects.get("effects", {}),
                        }
                    )
            except Exception:
                pass

        # ── v3: LLM Simulation Layer ──

        # Capture pre-turn morale for all factions (v2 may have changed it)
        pre_morale: dict[str, int] = {}
        for fid, f in ws.factions.items():
            if getattr(f, "is_active", True):
                pre_morale[fid] = getattr(f, "morale_actual", 50)

        # Build memory context
        room_id = getattr(self, "_room_id", "default")
        turn_history: list[dict] = []
        epoch_effects: list[dict] = []
        if self.turn_memory:
            self.turn_memory.clean_future_turns(room_id, ws.turn_number)
            turn_history = self.turn_memory.get_recent_turns(room_id, n=10)
            epoch_effects = self.turn_memory.get_persistent_effects(room_id)

        # Step 5: LLM nonlinear simulation
        llm_delta = {}
        _v3_tokens = {"prompt": 0, "completion": 0, "total": 0}
        if self.world_simulator and self.world_simulator.llm_available:
            # Track v3 LLM tokens for usage reporting
            v3_llm = getattr(self.world_simulator, "llm", None)
            _v3_pre = v3_llm.total_all_tokens if v3_llm and hasattr(v3_llm, "total_all_tokens") else 0

            llm_delta = self.world_simulator.simulate(
                ws,
                player_commands,
                player_decision,
                baseline_result,
                turn_history,
                epoch_effects,
                pre_morale=pre_morale,
            )

            if v3_llm and hasattr(v3_llm, "total_all_tokens"):
                _v3_tokens["total"] = v3_llm.total_all_tokens - _v3_pre

        # Step 6: Guardrail validation
        guardrail_result = {"accepted": True, "sanitized_delta": llm_delta, "warnings": []}
        if self.guardrail and llm_delta:
            guardrail_result = self.guardrail.validate(llm_delta, ws, baseline_result)

        # Step 7: Apply validated delta
        state_summary: dict = {}
        if guardrail_result["accepted"] and guardrail_result["sanitized_delta"]:
            state_summary = self.state_applier.apply(guardrail_result["sanitized_delta"], ws)

        # Update baseline_result with LLM overrides for narrative generation
        baseline_result.player_decision = player_decision
        baseline_result.player_commands = list(player_commands)
        sanitized = guardrail_result["sanitized_delta"]
        baseline_result._v3_delta = sanitized  # accessible by NarrativeEngine

        # Step 8: Record turn memory
        season_cn = current_season.cn if hasattr(current_season, "cn") else str(current_season)

        # Collect persistent effects from morale events
        persistent_effects = []
        if sanitized:
            for me in sanitized.get("morale_events", []):
                note = me.get("persistent_note", "")
                if note:
                    persistent_effects.append(
                        {
                            "note": note,
                            "turn": ws.turn_number,
                            "faction": me.get("faction", ""),
                        }
                    )

        # Build key events list
        key_events = []
        for bo in sanitized.get("battle_overrides", []):
            key_events.append(f"战斗@{bo.get('location', '?')}: {bo.get('llm_result', '?')}")
        for pe in sanitized.get("political_events", []):
            key_events.append(f"政事@{pe.get('faction', '?')}: {pe.get('type', '?')}")
        for me in sanitized.get("morale_events", []):
            ch = me.get("change", 0)
            if abs(ch) >= 3:
                key_events.append(f"民心@{me.get('faction', '?')}: {ch:+d} ({me.get('reason', '?')[:30]})")

        player = ws.factions.get(ws.player_faction_id)
        state_snapshot = {
            "morale": getattr(player, "morale_actual", 0) if player else 0,
            "territories": len(player.territories) if player else 0,
            "strength": getattr(player, "strength_actual", 0) if player else 0,
            "treasury": player.treasury if player else 0,
            "food": player.food if player else 0,
        }

        if self.turn_memory and player_decision:
            self.turn_memory.record_turn(
                room_id,
                ws.turn_number,
                current_year,
                season_cn,
                player_decision,
                outcome_summary="; ".join(key_events) if key_events else "平和无事",
                key_events=key_events,
                state_snapshot=state_snapshot,
                persistent_effects=persistent_effects,
            )

        # ── Narrative Generation ──

        narrative_text = ""
        new_choices: list[str] = []
        averted_list = list(ws.averted_events)
        if self.history_engine:
            averted_list = list(set(averted_list) | self.history_engine._blocked_downstream)

        # Build v3-aware narrative
        narrative_seeds = sanitized.get("narrative_seeds", []) if sanitized else []
        npc_actions_list = sanitized.get("npc_faction_actions", []) if sanitized else []

        if self.narrative_engine and self.narrative_engine.is_available:
            # Inject v3 delta into baseline_result so narrative engine includes it
            if sanitized:
                _inject_v3_into_baseline(baseline_result, sanitized)

            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                future_narrative = executor.submit(
                    self.narrative_engine.generate_turn_narrative,
                    baseline_result,
                    deviation=ws.player_deviation,
                    averted_events=averted_list,
                    world_state=ws,
                    room_id=room_id,
                )
                future_suggestions = executor.submit(
                    self.narrative_engine.generate_plan_suggestions, ws, ws.player_faction_id
                )

                try:
                    with _suppress_stderr():
                        narrative_text = future_narrative.result(timeout=30)
                except Exception:
                    narrative_text = ""

                try:
                    with _suppress_stderr():
                        new_choices = future_suggestions.result(timeout=30)
                except Exception:
                    new_choices = self._offline_v2_suggestions()
        else:
            new_choices = self._offline_v2_suggestions()

        # Build v3-style narrative from seeds if available, otherwise fall back to v2
        if narrative_seeds:
            # Build narrative header
            header_lines = [
                f"### {current_year}年{season_cn} · 大事纪",
                f"建安{current_year - 196}年{season_cn}，天下纷争未休。",
                "",
            ]
            # Resource summary
            if player:
                player.food - state_snapshot.get("food", player.food)
                player.treasury - state_snapshot.get("treasury", player.treasury)
                header_lines.append(
                    f"**{player.name}** | 兵力{player.strength_actual:,} | "
                    f"资金{player.treasury:,} | 粮草{player.food:,} | "
                    f"民心{getattr(player, 'morale_actual', '?')}"
                )
                header_lines.append("")

            # v3 narrative seeds as the main body
            body_lines = []
            for seed in narrative_seeds[:8]:
                body_lines.append(f"> {seed}")
            body_lines.append("")

            # NPC activity summary
            if npc_actions_list:
                npc_lines = ["**天下动向**"]
                for na in npc_actions_list[:4]:
                    faction_id = na.get("faction", "?")
                    faction_obj = ws.factions.get(faction_id)
                    faction_name = faction_obj.name if faction_obj else faction_id
                    action_cn = {
                        "attack": "进攻",
                        "defend": "防守",
                        "recruit": "募兵",
                        "develop": "发展",
                        "ally": "结盟",
                        "strategic_retreat": "撤退",
                        "wait": "休整",
                    }.get(na.get("action", ""), na.get("action", ""))
                    reason = na.get("reasoning", "")
                    npc_lines.append(f"- {faction_name}**{action_cn}**：{reason}")
                body_lines.append("")
                body_lines.extend(npc_lines)

            # Political events
            pol_events = sanitized.get("political_events", []) if sanitized else []
            if pol_events:
                body_lines.append("")
                body_lines.append("**朝堂政事**")
                for pe in pol_events[:3]:
                    desc = pe.get("description", "")
                    if desc:
                        body_lines.append(f"- {desc}")

            narrative_text = "\n".join(header_lines) + "\n".join(body_lines)
            if narrative_text and not narrative_text.endswith("\n"):
                narrative_text += "\n"
        elif not narrative_text:
            narrative_text = self._offline_v2_narrative(baseline_result)

        # Build aftermath/summary
        aftermath_parts = []
        if player:
            player_morale = getattr(player, "morale_actual", 0)
            aftermath_parts.append(f"民心{player_morale}")
            aftermath_parts.append(f"兵力{player.strength_actual:,}")
        if key_events:
            aftermath_parts.append(" | ".join(key_events[:3]))
        aftermath_text = "。".join(aftermath_parts) + "。" if aftermath_parts else "局势已定。"

        # Token usage tracking (v3-specific)
        _main_usage = {}
        if self.narrative_engine and self.narrative_engine.is_available:
            llm_narr = getattr(self.narrative_engine, "llm", None)
            if llm_narr and hasattr(llm_narr, "total_all_tokens"):
                _main_usage["narrative_tokens"] = 0  # tracked in main llm

        _usage = {
            "intent_tokens": 0,  # IntentParser (in main llm)
            "command_tokens": 0,  # CommandValidator (free)
            "npc_tokens": 0,  # NPC AI (not separately tracked)
            "sim_tokens": _v3_tokens.get("total", 0),  # v3 WorldSimulator
            "narrative_tokens": 0,
        }

        # ── Build result dict (v2-compatible + v3 extras) ──

        game_over = _check_player_game_over(ws, player)

        self._save_v2()

        # Log turn
        try:
            from ..engine.log_exporter import append_to_session_log

            append_to_session_log(ws.turn_number, current_year, season_cn, player_decision, {})
        except Exception:
            pass

        self._log_simulation_history()

        return {
            "narrative": narrative_text,
            "aftermath": aftermath_text,
            "summary": aftermath_text,
            "bureaucracy": [
                {"department": "军机处", "official": "参军", "action": f"执行{len(player_commands)}项军令"}
            ],
            "state_changes": state_summary,
            "new_choices": new_choices,
            "events_occurred": [],
            "npc_actions": [na.get("reasoning", "") for na in npc_actions_list],
            "seeds": [{"title": "v3 推演", "description": s[:80]} for s in narrative_seeds[:4]],
            "npc_reactions": [],
            "game_over": game_over,
            "world_state": ws,
            "_usage": _usage,
            "v3_metadata": {
                "delta_accepted": guardrail_result["accepted"],
                "warnings": len(guardrail_result.get("warnings", [])),
                "narrative_seeds": len(narrative_seeds),
                "llm_delta_keys": list(llm_delta.keys()) if llm_delta else [],
                "sim_tokens": _v3_tokens.get("total", 0),
            },
        }
    def _normalize_seeds(self, raw_seeds: list) -> list[dict]:
        """Normalize narrative_seeds from LLM — strings → {title: str} dicts."""
        result = []
        for s in raw_seeds or []:
            if isinstance(s, dict):
                result.append(s)
            elif isinstance(s, str):
                result.append({"title": s, "trigger_after": "?", "description": ""})
        return result
    def _process_turn_macro(self, player_decision: str) -> dict:
        """Macro historical engine — quarterly policy simulation.

        Pipeline: PolicyParser → PolicyValidator → QuarterlyEngine
        → BlackSwanInjector → MacroPolicyEngine → Narrative
        """
        ws = self.world_state_v2

        # --- Debug logger: collect LLM calls & sim events for Postgres ---
        _debug_log = None
        _session_id = getattr(self, "_debug_session_id", "")
        if _session_id:
            from ..engine.debug_logger import TurnLogCollector

            _debug_log = TurnLogCollector(
                _session_id,
                ws.turn_number + 1,
            )
            _debug_log.event(
                "turn_start",
                {
                    "turn": ws.turn_number + 1,
                    "year": ws.year,
                    "season": str(ws.season),
                    "player_decision": player_decision[:200],
                },
            )
            import logging

            logging.getLogger("histrategy").info(
                f"Debug log initialized for session={_session_id[:12]}... turn={ws.turn_number + 1}"
            )

        # Step 1: Parse player policy
        policy_commands = []
        if self._macro_parser:
            policy_commands = self._macro_parser.parse(player_decision, ws.player_faction_id)
        self._last_player_decision = player_decision

        # Step 2: Validate
        if self._macro_validator:
            policy_commands = self._macro_validator.validate(policy_commands, ws)

        # Step 3: Deterministic quarterly baseline
        quarter = 0
        season_str = str(ws.season).lower()
        for name, q in [
            ("spring", 0),
            ("summer", 1),
            ("autumn", 2),
            ("winter", 3),
            ("春", 0),
            ("夏", 1),
            ("秋", 2),
            ("冬", 3),
        ]:
            if name in season_str:
                quarter = q
                break

        baseline = self._quarterly_engine.execute_quarter(
            ws,
            policy_commands,
            ws.year,
            quarter,
        )
        baseline.player_decision = player_decision

        # Step 4: Black swan events
        bs_proposals = []
        if self._black_swan and self.history_engine:
            try:
                bs_proposals = self._black_swan.check_events(
                    ws.year,
                    ws.season,
                    ws,
                    deviation=ws.player_deviation,
                    history_engine=self.history_engine,
                )
                for prop in bs_proposals:
                    if prop.get("triggered"):
                        self._black_swan.inject_event(
                            prop["event_id"],
                            prop.get("effects", {}),
                            ws,
                        )
                        if _debug_log:
                            _debug_log.event(
                                "black_swan",
                                {
                                    "event_id": prop["event_id"],
                                    "effects": prop.get("effects", {}),
                                },
                            )
            except Exception as e:
                import logging

                logging.getLogger("histrategy").warning(f"Black swan check/inject failed: {e}")

        # Step 5: LLM MacroPolicyEngine
        llm_delta = {}
        _sim_tokens = 0
        if self._macro_sim and self._macro_sim.llm_available:
            mlm = getattr(self._macro_sim, "llm", None)
            _pre = mlm.total_all_tokens if mlm and hasattr(mlm, "total_all_tokens") else 0

            llm_delta = self._macro_sim.simulate(
                ws,
                policy_commands,
                player_decision,
                baseline,
                bs_proposals,
                turn_memory=getattr(self, "_turn_summaries", [])[-8:],  # last 8 quarters
            )

            if mlm and hasattr(mlm, "total_all_tokens"):
                _sim_tokens = mlm.total_all_tokens - _pre

            if _debug_log and _sim_tokens > 0:
                _debug_log.llm(
                    call_type="macro_simulate",
                    provider=getattr(mlm, "provider", "") if mlm else "",
                    model=getattr(mlm, "model", "") if mlm else "",
                    total_tokens=_sim_tokens,
                    latency_ms=0,
                )

        # Step 6: Apply LLM delta
        if llm_delta:
            for me in llm_delta.get("morale_events", []):
                fid = me.get("faction", "")
                ch = me.get("change", 0)
                if fid in ws.factions and ch:
                    cur = getattr(ws.factions[fid], "morale_actual", 50)
                    ws.factions[fid].morale_actual = max(0, min(100, cur + ch))
            # Normalize faction/territory IDs from LLM output
            faction_id_map = _build_faction_id_map(ws)
            territory_id_map = _build_territory_id_map(ws)
            for br in llm_delta.get("battle_results", []):
                if br.get("territory_captured"):
                    loc_raw = br.get("location", "")
                    att_raw = br.get("attacker", "")
                    loc = territory_id_map.get(loc_raw, loc_raw)
                    att = faction_id_map.get(att_raw, att_raw)
                    if loc in ws.territories and att in ws.factions:
                        old = ws.territories[loc].owner_id
                        ws.territories[loc].owner_id = att
                        if old in ws.factions and loc in ws.factions[old].territories:
                            ws.factions[old].territories.remove(loc)
                        if loc not in ws.factions[att].territories:
                            ws.factions[att].territories.append(loc)
                        # Absorb ~20% of defender's troops stationed in captured city
                        if old and old in ws.factions:
                            old_faction = ws.factions[old]
                            absorbed = int(old_faction.strength_actual * 0.2 / max(len(old_faction.territories), 1))
                            if absorbed > 0:
                                old_faction.strength_actual -= absorbed
                                ws.factions[att].strength_actual = (
                                    getattr(ws.factions[att], "strength_actual", 0) + absorbed
                                )
            # Auto-surrender: factions with morale < 15 and ≤ 1 territory
            for fid, f in list(ws.factions.items()):
                if fid == ws.player_faction_id:
                    continue
                if getattr(f, "is_active", True) and getattr(f, "morale_actual", 50) < 15 and len(f.territories) <= 1:
                    f.is_active = False
                    # Transfer last territory to nearest neighbor
                    if f.territories:
                        last_t = f.territories[0]
                        neighbors = getattr(ws.territories[last_t], "neighbors", [])
                        for nid in neighbors:
                            if nid in ws.territories:
                                n_owner = ws.territories[nid].owner_id
                                if n_owner in ws.factions and getattr(ws.factions[n_owner], "is_active", True):
                                    ws.territories[last_t].owner_id = n_owner
                                    if last_t not in ws.factions[n_owner].territories:
                                        ws.factions[n_owner].territories.append(last_t)
                                    break
            for br in llm_delta.get("battle_results", []):
                if not br.get("territory_captured") and br.get("defender_faction"):
                    # Handle "defeated" factions — mark inactive
                    def_raw = br.get("defender_faction", "") or br.get("defender", "")
                    def_id = faction_id_map.get(def_raw, def_raw)
                    if (
                        def_id in ws.factions
                        and def_id != ws.player_faction_id
                        and (br.get("result") in ("attack_win", "rout") or br.get("is_total_defeat"))
                    ):
                        ws.factions[def_id].is_active = False
                        # Transfer remaining territories to victor
                        att_raw = br.get("attacker", "")
                        att = faction_id_map.get(att_raw, att_raw)
                        if att in ws.factions:
                            for t_loc in list(ws.factions[def_id].territories):
                                ws.territories[t_loc].owner_id = att
                                ws.factions[def_id].territories.remove(t_loc)
                                if t_loc not in ws.factions[att].territories:
                                    ws.factions[att].territories.append(t_loc)

        # Step 6.5: Apply NPC faction independent actions
        if llm_delta:
            npc_faction_actions = llm_delta.get("npc_faction_actions", [])
            for nfa in npc_faction_actions:
                fid = nfa.get("faction", "")
                fid = faction_id_map.get(fid, fid)
                if fid not in ws.factions or fid == ws.player_faction_id:
                    continue
                faction = ws.factions[fid]
                action_type = nfa.get("action_type", "none")
                params = nfa.get("params", {})

                if action_type == "conscript":
                    amount = params.get("amount", 5000)
                    cost = int(amount * 0.5)
                    if faction.treasury >= cost:
                        faction.strength_actual = getattr(faction, "strength_actual", 0) + amount
                        faction.treasury -= cost
                elif action_type == "develop":
                    # Boost economy in a random territory
                    if faction.territories:
                        faction.treasury -= params.get("cost", 300)
                        faction.economy_actual = min(100, getattr(faction, "economy_actual", 50) + 5)
                elif action_type == "diplomacy":
                    target = nfa.get("target", "")
                    target = faction_id_map.get(target, target)
                    if target in ws.factions:
                        rel_delta = params.get("relation_delta", 10)
                        # Update relations if the faction has a relations dict
                        if hasattr(faction, "relations"):
                            cur = faction.relations.get(target, 0)
                            faction.relations[target] = max(-100, min(100, cur + rel_delta))
                elif action_type == "tax":
                    # NPC adjusts tax rate
                    new_rate = params.get("rate", 0.3)
                    if hasattr(faction, "tax_rate"):
                        faction.tax_rate = max(0.05, min(0.6, new_rate))

        # Step 7: Generate narrative (from LLM seeds + faction state)
        narrative_text = ""
        new_choices = []

        # Build macro-aware narrative from LLM delta
        narrative_parts = []
        if llm_delta:
            seeds = llm_delta.get("narrative_seeds", [])
            for s in seeds:
                narrative_parts.append(f"### {s}")

            battles = llm_delta.get("battle_results", [])
            for b in battles:
                n = b.get("narrative", "")
                if n:
                    narrative_parts.append(f"> {n}")

            diplo = llm_delta.get("diplomatic_reactions", [])
            for d in diplo:
                act = d.get("action", "")
                if act:
                    narrative_parts.append(f"**{d.get('faction', '?')}**: {act}")

            polit = llm_delta.get("political_events", [])
            for p in polit:
                desc = p.get("description", "")
                if desc:
                    narrative_parts.append(f"🏛 {desc}")

            # NPC faction independent actions
            npc_fa = llm_delta.get("npc_faction_actions", [])
            for nfa in npc_fa:
                narr = nfa.get("narrative", "")
                if narr:
                    narrative_parts.append(f"⚡ {narr}")

        narrative_text = (
            "\n\n".join(narrative_parts)
            if narrative_parts
            else (
                "All is quiet across the realm.\n"
                if getattr(self, "_scenario_language", "zh") == "en"
                else "天下大势，波澜不惊。\n"
            )
        )

        # Generate plan suggestions
        if ws.turn_number <= 1:
            # ── First turn: hard-coded suggestions (no LLM needed) ──
            new_choices = FIRST_TURN_SUGGESTIONS.get(
                ws.player_faction_id,
                FIRST_TURN_SUGGESTIONS["cao"],
            )
        elif self.narrative_engine and self.narrative_engine.is_available:
            with contextlib.suppress(Exception):
                new_choices = self.narrative_engine.generate_plan_suggestions(ws, ws.player_faction_id)

        # Step 8: Aftermath (from actual faction state, not stale baseline)
        pf = ws.factions.get(ws.player_faction_id)
        parts = []
        is_en = getattr(self, "_scenario_language", "zh") == "en"
        if pf:
            if is_en:
                parts.append(f"Gold:{pf.treasury}")
                parts.append(f"Food:{pf.food}")
                parts.append(f"Morale:{getattr(pf, 'morale_actual', '?')}")
                territories = list(pf.territories) if pf.territories else []
                parts.append(f"Territories:{len(territories)}")
            else:
                parts.append(f"资金:{pf.treasury}")
                parts.append(f"粮草:{pf.food}")
                parts.append(f"民心:{getattr(pf, 'morale_actual', '?')}")
                territories = list(pf.territories) if pf.territories else []
                parts.append(f"领地:{len(territories)}")
        aftermath = "This quarter: " if is_en else "本季度："
        sep = ", " if is_en else "，"
        aftermath += sep.join(parts) + ("." if is_en else "。")

        # Add LLM narrative summary if available
        if narrative_parts and len(narrative_parts) > 1:
            suffix = "." if is_en else "。"
            aftermath += f" {narrative_parts[0].replace('### ', '')}{suffix}"

        # Knowledge cards
        kcards = []
        if llm_delta:
            kcards = self._knowledge_base.get_cards_for_events(llm_delta.get("knowledge_cards", []))
        ksummaries = []
        for kc in kcards[:3]:
            if isinstance(kc, dict):
                topic = kc.get("topic", "")
                logic = kc.get("engine_logic", "")
            else:
                topic = getattr(kc, "topic", "")
                logic = getattr(kc, "engine_logic", "")
            if topic:
                ksummaries.append(f"📚 {topic}: {logic}")

        # NPC data — normalize to plain strings (portal frontend expects strings,
        # React crashes with "a.match is not a function" on dict objects)
        npc_acts_raw = llm_delta.get("npc_actions", []) if llm_delta else []
        npc_acts = []
        for a in npc_acts_raw:
            if isinstance(a, dict):
                faction = a.get("faction", "?")
                action = a.get("action", a.get("reasoning", str(a)))
                npc_acts.append(f"{faction}: {action}")
            elif isinstance(a, str):
                npc_acts.append(a)
        npc_reacts_raw = llm_delta.get("diplomatic_reactions", []) if llm_delta else []
        npc_reacts = []
        for r in npc_reacts_raw:
            if isinstance(r, dict):
                faction = r.get("faction", "?")
                action = r.get("action", "")
                if action:
                    npc_reacts.append(f"{faction}: {action}")
            elif isinstance(r, str):
                npc_reacts.append(r)
        # Also include npc_faction_actions as NPC actions for frontend
        npc_fa = llm_delta.get("npc_faction_actions", []) if llm_delta else []
        for nfa in npc_fa:
            narr = nfa.get("narrative", "")
            if narr:
                npc_acts.append(f"{nfa.get('faction', '?')}: {narr}")

        # Game over?
        pf = ws.factions.get(ws.player_faction_id)
        game_over = not getattr(pf, "is_active", True) if pf else False

        result = {
            "narrative": narrative_text,
            "aftermath": aftermath,
            "bureaucracy": [
                {
                    "department": "尚书台",
                    "official": "尚书令",
                    "action": f"执行{len(policy_commands)}项策令",
                }
            ],
            "state_changes": {
                "food": baseline.resource_changes.get(ws.player_faction_id, {}).get("food_delta", 0),
                "treasury": baseline.resource_changes.get(ws.player_faction_id, {}).get("tax_revenue", 0),
                "morale": baseline.morale_delta.get(ws.player_faction_id, 0),
            },
            "_usage": {"command_tokens": _sim_tokens, "plan_tokens": 0, "npc_tokens": 0, "sim_tokens": _sim_tokens},
            "seeds": self._normalize_seeds(llm_delta.get("narrative_seeds", []) if llm_delta else []),
            "npc_reactions": npc_reacts,
            "npc_actions": npc_acts,
            "events_occurred": [p.get("event_id", "") for p in bs_proposals if p.get("triggered")],
            "new_choices": new_choices,
            "game_over": game_over,
            "world_state": ws,
            "knowledge_cards": ksummaries,
            "black_swan_events": [p["event_id"] for p in bs_proposals if p.get("triggered")],
        }

        # Advance turn and season
        ws.turn_number += 1
        _advance_season_and_year(ws)

        # ── Record turn summary for LLM context in future turns ──
        narrative_seeds = llm_delta.get("narrative_seeds", []) if llm_delta else []
        summary_text = "; ".join(narrative_seeds[:2]) if narrative_seeds else narrative_text[:200]
        if not hasattr(self, "_turn_summaries"):
            self._turn_summaries = []
        season_val = ws.season.cn if hasattr(ws.season, "cn") else ws.season
        self._turn_summaries.append(
            {
                "outcome_summary": (
                    f"[{ws.year}年{season_val}] "
                    f"{player_decision[:200]}{'...' if len(player_decision) > 200 else ''}"
                    f" → {summary_text[:300]}{'...' if len(summary_text) > 300 else ''}"
                ),
                "turn": ws.turn_number,
            }
        )
        # Keep only last 8 turns to bound context growth
        if len(self._turn_summaries) > 8:
            self._turn_summaries = self._turn_summaries[-8:]

        # Attach debug log data to result for API layer to persist
        if _debug_log:
            result["_debug_log"] = {
                "llm_calls": _debug_log._llm_calls,
                "sim_events": _debug_log._sim_events,
            }

        self._save_v2()
        return result

    # ── Symmetric Multiplayer Path ───────────────────────────
    # Bridges new GameRoom/FactionSlot/DecisionBus/QuarterlyResolver
    # with the existing API response format. The single-player flow
    # internally uses this symmetric architecture for true NPC autonomy.
    def process_turn_symmetric(self, player_decision: str) -> dict:
        """Process a turn using the symmetric multi-faction architecture.

        Internally creates a GameRoom with 1 human + N AI slots,
        each AI generates its own independent LLM decision,
        then all decisions are resolved together in one quarter.
        """
        import uuid as _uuid

        from ..engine.decision_bus import collect_all_decisions
        from ..engine.game_room import GameRoom, RoomPhase
        from ..engine.quarterly_resolver import QuarterlyResolver

        ws = self.world_state_v2
        faction_id = ws.player_faction_id

        # ── Build GameRoom from engine state ──
        room = GameRoom(
            id=getattr(self, "_room_id", str(_uuid.uuid4())),
            scenario=self.scenario,
            year=ws.year,
            season=ws.season.cn if hasattr(ws.season, "cn") else str(ws.season),
            quarter_number=ws.turn_number,
            phase=RoomPhase.WAITING,
        )

        # Add human slot
        from ..engine.faction_slot import create_ai_slot, create_human_slot

        room.slots[faction_id] = create_human_slot(faction_id)

        # Add AI slots for other active factions
        for fid, f in ws.factions.items():
            if fid == faction_id or not getattr(f, "is_active", True):
                continue
            room.slots[fid] = create_ai_slot(fid)

        # Carry forward turn summaries
        if hasattr(self, "_turn_summaries"):
            room.turn_summaries = list(self._turn_summaries[-8:])

        room.start_game()

        # ── Submit human decision ──
        human_slot = room.slots.get(faction_id)
        if human_slot:
            human_slot.submit_decision(player_decision)

        # ── Collect all decisions (AI via parallel LLM) ──
        llm = getattr(self.narrative_engine, "llm", None) if self.narrative_engine else None
        if not llm and hasattr(self, "_macro_sim"):
            llm = getattr(self._macro_sim, "llm", None)

        decisions = collect_all_decisions(
            room,
            ws,
            llm=llm,
            turn_memory=room.turn_summaries,
            lang=getattr(room, "metadata", {}).get("lang", "zh"),
        )

        # ── Resolve quarter ──
        resolver = QuarterlyResolver(
            intent_parser=getattr(self, "_macro_parser", None),
            turn_controller=self.turn_controller,
            history_engine=self.history_engine,
            macro_policy_engine=getattr(self, "_macro_sim", None),
            narrative_engine=self.narrative_engine,
            black_swan_injector=getattr(self, "_black_swan", None),
            guardrail_validator=getattr(self, "guardrail_validator", None),
            state_applier=getattr(self, "state_applier", None),
        )

        quarterly = resolver.resolve(room, ws, decisions, llm=llm)

        # ── Add turn summary ──
        if quarterly.turn_summary:
            if not hasattr(self, "_turn_summaries"):
                self._turn_summaries = []
            self._turn_summaries.append(quarterly.turn_summary)
            if len(self._turn_summaries) > 8:
                self._turn_summaries = self._turn_summaries[-8:]

        # ── Collect NPC actions for response ──
        npc_actions = []
        is_en = getattr(self, "_scenario_language", "zh") == "en"
        for fid, dr in decisions.items():
            if fid != faction_id:
                faction = ws.factions.get(fid)
                name = (faction.name_en if is_en and faction.name_en else faction.name) if faction else fid
                npc_actions.append(f"{name}: {dr.decision_text[:80]}")

        # ── Advance season/year ──
        _advance_season_and_year(ws)
        ws.turn_number += 1

        # ── Game over check ──
        game_over = None
        pf = ws.factions.get(faction_id)
        if not pf or not pf.is_active:
            game_over = True

        # ── Build response in old format ──
        narrative = quarterly.narratives.get(faction_id, "天下大势，波澜不惊。\n")

        # Per-faction narratives summary
        if len(quarterly.narratives) > 1:
            other_narratives = []
            for fid, narr in quarterly.narratives.items():
                if fid != faction_id and narr:
                    faction = ws.factions.get(fid)
                    name = faction.name if faction else fid
                    other_narratives.append(f"**{name}**: {narr[:120]}")
            if other_narratives:
                narrative += "\n\n---\n**天下动向**\n\n" + "\n\n".join(other_narratives[:3])

        aftermath = "; ".join(npc_actions[:3]) if npc_actions else "天下平静。"

        result = {
            "narrative": narrative,
            "aftermath": aftermath,
            "bureaucracy": [
                {
                    "department": "尚书台",
                    "official": "尚书令",
                    "action": f"执行{len(decisions)}个势力策令",
                }
            ],
            "state_changes": quarterly.state_changes.get(faction_id, {}),
            "_usage": {"command_tokens": 0, "plan_tokens": 0, "npc_tokens": 0, "sim_tokens": 0},
            "seeds": [],
            "npc_reactions": [],
            "npc_actions": npc_actions,
            "events_occurred": [e.get("event_id", "") for e in quarterly.history_events],
            "new_choices": [],
            "game_over": game_over,
            "world_state": ws,
            "knowledge_cards": [],
        }

        self._save_v2()
        return result

    def _process_turn_v1(self, player_decision: str) -> dict:
        """v1 turn processing (unchanged)."""
        sim_result = self.sim_engine.simulate(self.world_state, player_decision)

        if sim_result.world_state:
            self.world_state = sim_result.world_state

        result_dict = {
            "narrative": sim_result.narrative,
            "aftermath": sim_result.aftermath,
            "bureaucracy": sim_result.bureaucracy,
            "state_changes": (
                sim_result.state_changes or (sim_result.short_term.get("changes", {}) if sim_result.short_term else {})
            ),
            "seeds": sim_result.seeds,
            "npc_reactions": sim_result.npc_reactions or sim_result.npc_actions or [],
            "events_occurred": sim_result.events_occurred or [],
            "game_over": sim_result.game_over,
            "world_state": sim_result.world_state,
        }

        # Process NPC dramatic events
        from ..engine.npc_events import process_npc_drastic_events

        npc_evt_res = process_npc_drastic_events(self.world_state)

        if npc_evt_res["events_occurred"]:
            result_dict["events_occurred"].extend(npc_evt_res["events_occurred"])
            result_dict["npc_reactions"].extend(npc_evt_res["npc_reactions"])
            sc = result_dict["state_changes"]
            for k, val in npc_evt_res["state_changes"].items():
                if val:
                    sc[k] = sc.get(k, 0) + val
            betrayal_aftermaths = "\n\n" + "\n".join(npc_evt_res["events_occurred"])
            result_dict["aftermath"] = (result_dict["aftermath"] or "") + betrayal_aftermaths
            save_world(self.world_state)

        try:
            from ..engine.log_exporter import append_to_session_log

            append_to_session_log(
                self.world_state.turn,
                self.world_state.year,
                self.world_state.current_season,
                player_decision,
                result_dict,
            )
        except Exception:
            pass

        self._log_simulation_history()

        return result_dict

