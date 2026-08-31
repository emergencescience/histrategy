"""
QuarterlyResolver — 对称多 faction 季度引擎。

替代旧的 GameEngine._process_turn_macro()。
接收所有 faction 的决策，统一执行季度模拟：

1. 解析所有势力决策（人类 → IntentParser，AI → 已预解析）
2. 确定性基线 (TurnController multi-faction)
3. 黑天鹅事件注入 (BlackSwanInjector)
4. LLM 宏观模拟 (MacroPolicyEngine with all decisions)
5. Per-faction 叙事生成 (parallel NarrativeEngine)
6. 状态持久化 (SQL)
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from .decision_bus import DecisionResult

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState

    from histrategy.engine.game_room import GameRoom
    from histrategy.llm.adapter import LLMAdapter

logger = logging.getLogger("histrategy.quarterly")

# ── 内部引擎引用（延迟导入以避免循环依赖） ──


_SCENARIO_DISPLAY = {
    "nanming": "《山河鼎革》",
    "three-kingdoms": "《三國志略》",
    "rome-triumvirate": "《凯撒余烬》",
}


def _get_max_quarters(scenario: str) -> int:
    """Read scenario.toml [engine] max_quarters. 0 = unlimited."""
    try:
        import tomllib
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        fp = root / "scenarios" / scenario / "scenario.toml"
        if fp.is_file():
            cfg = tomllib.loads(fp.read_text())
            return int(cfg.get("engine", {}).get("max_quarters", 0) or 0)
    except Exception as exc:
        logger.warning("Failed to read max_quarters for scenario=%s: %s", scenario, exc)
    return 0


def _build_conclusion(room, ws) -> dict:
    """生成剧终 game_over 消息（历史偏移结算为后续增强）。"""
    scenario = getattr(room, "scenario", "")
    name = _SCENARIO_DISPLAY.get(scenario, "本作")
    year = getattr(ws, "year", getattr(room, "year", ""))
    return {
        "type": "conclusion",
        "message": (
            f"# 🎌 {name} · 历史帷幕落下\n\n"
            f"公元 {year} 年，这段由你亲手改写的历史走到了既定的终点。\n\n"
            "乱世之中，你的每一个决策都曾改变山河的走向。\n"
            "感谢你的运筹与坚守。\n\n"
            "（终局结算：历史偏移对比与成就评语，将在后续版本呈现。）"
        ),
    }


def _apply_npc_structured_recruitment(world_state, all_commands: dict, baseline) -> int:
    """H36k: Apply NPC recruit/conscript/disband from structured LLM decisions.

    Replaces the old deterministic execute_npc_recruitment() which ignored
    LLM intent. Each NPC's structured commands drive recruitment:
    - recruit: adds troops, deducts gold (0.5 per soldier)
    - conscript: adds troops, deducts gold (0.3 per soldier, cheaper but morale hit)
    - disband: removes troops, adds gold back (0.2 per soldier)

    All amounts are CLAMPED to actual faction limits (treasury, population).

    Returns:
        Number of factions that had at least one recruitment action applied.
        0 means NO recruitment happened — caller should fall back to deterministic.
    """
    # H36r: Accept both WorldState classes (histrategy_engine.world and
    # histrategy.state.world_state). The isinstance check was rejecting
    # the histrategy.state.world_state.WorldState that create_initial_world()
    # returns, causing ALL NPC recruitment to be silently skipped.
    try:
        from histrategy_engine.world import WorldState as _EngineWS
        _has_engine_ws = isinstance(world_state, _EngineWS)
    except ImportError:
        _has_engine_ws = False

    # Check for factions dict (duck-type)
    if not hasattr(world_state, "factions"):
        return 0

    player_fid = getattr(world_state, "player_faction_id", None)
    events = getattr(baseline, "notable_events", []) if baseline else []
    recruited_count = 0

    # H36r: quick debug — use logger to ensure visibility
    import logging
    _log = logging.getLogger("histrategy.recruit")
    npc_fids = [fid for fid in all_commands if fid != player_fid]
    total = sum(len(v) for k, v in all_commands.items() if k != player_fid)
    _log.warning("H36R_ENTER player=%s npcs=%s cmds=%d has_factions=%s",
                 player_fid, npc_fids, total, hasattr(world_state, 'factions'))
    for fid in npc_fids:
        cmds = all_commands.get(fid, [])
        types = [c.get('type','?') if isinstance(c,dict) else type(c).__name__ for c in cmds[:3]]
        _log.warning("H36R_CMDS %s: %s", fid, types)

    for fid, commands in all_commands.items():
        if fid == player_fid:
            continue
        faction = world_state.factions.get(fid)
        if not faction or not getattr(faction, "is_active", True):
            continue

        treasury = getattr(faction, "treasury", 0) or 0
        strength = getattr(faction, "strength_actual", 0) or 0
        population = getattr(faction, "population", 0) or 0
        morale = getattr(faction, "morale_actual", 50) or 50

        for cmd in commands:
            if not isinstance(cmd, dict):
                continue
            cmd_type = cmd.get("type", "")
            _log.debug("H36R_CMD %s type=%s", fid, cmd_type)
            params = cmd.get("params", {}) if isinstance(cmd.get("params"), dict) else {}

            if cmd_type == "recruit":
                amount = int(params.get("amount", 0))
                if amount <= 0:
                    continue
                # Clamp to 3% of population
                max_recruit = int(population * 0.03)
                # H38c: 常备军上限 — 总兵力不得超过人口的 15%（防 NPC 逐季堆兵通胀）
                _ceiling_headroom = max(0, int(population * 0.15) - strength)
                amount = min(amount, max_recruit, _ceiling_headroom)
                # Clamp to treasury (0.5 gold per soldier)
                cost = amount * 0.5
                if cost > treasury:
                    amount = int(treasury / 0.5)
                    cost = amount * 0.5
                if amount < 50:  # too small, skip
                    continue
                strength += amount
                treasury -= cost
                faction.strength_actual = strength
                faction.treasury = treasury
                if events is not None:
                    events.append(f"{fid}从LLM决策征兵{amount}人（花费{cost:.0f}金）")
                recruited_count += 1

            elif cmd_type == "conscript":
                amount = int(params.get("amount", 0))
                if amount <= 0:
                    continue
                max_conscript = int(population * 0.02)
                # H38c: 常备军上限 — 同 recruit，总兵力不得超过人口的 15%
                _ceiling_headroom = max(0, int(population * 0.15) - strength)
                amount = min(amount, max_conscript, _ceiling_headroom)
                cost = amount * 0.3  # cheaper but morale hit
                if cost > treasury:
                    amount = int(treasury / 0.3)
                    cost = amount * 0.3
                if amount < 50:
                    continue
                strength += amount
                treasury -= cost
                morale = max(0, morale - 2)
                faction.strength_actual = strength
                faction.treasury = treasury
                faction.morale_actual = morale
                if events is not None:
                    events.append(f"{fid}从LLM决策紧急征召{amount}人（花费{cost:.0f}金，士气-2）")
                recruited_count += 1

            elif cmd_type == "disband":
                amount = int(params.get("amount", 0))
                if amount <= 0:
                    continue
                # H37c: guardrail — cap disband at 15% of current strength per quarter.
                # The npc_decision LLM decides the disband amount, but without a cap it
                # can disband 50%+ of an army in a single turn (observed troop crash).
                # recruit/conscript already cap at 3%/2% of population; disband gets a
                # symmetric 15%-of-strength cap so financial pressure can't vaporize an
                # army in one quarter.
                amount = min(amount, int(strength * 0.15), strength - 500)  # keep at least 500
                if amount < 50:
                    continue
                strength -= amount
                treasury += amount * 0.2
                population += amount
                faction.strength_actual = strength
                faction.treasury = treasury
                faction.population = population
                if events is not None:
                    events.append(f"{fid}从LLM决策裁军{amount}人（回金{amount*0.2:.0f}，人口+{amount}）")
                recruited_count += 1

    return recruited_count


def _log_faction_troops(ws, label: str, room_id: str = "") -> None:
    """H37d: Log all faction troops at a resolve() step to trace the troop crash."""
    import logging
    log = logging.getLogger("histrategy.trooptrace")
    if not hasattr(ws, "factions"):
        log.warning("[TROOPTRACE][room=%s] %s: (no factions)", room_id, label)
        return
    parts = []
    for fid, f in ws.factions.items():
        if not getattr(f, "is_active", True):
            continue
        parts.append(f"{fid}={getattr(f, 'strength_actual', 0)}")
    log.warning("[TROOPTRACE][room=%s] %s → %s", room_id, label, ", ".join(parts))


class QuarterlyResolver:
    """对称多 faction 季度引擎。

    这是整个对称多人引擎的「执行核心」。接收一个 GameRoom
    和所有 faction 的决策，执行完整的季度模拟。

    注意：此引擎对「单人类 + 多AI」和「多人类 + 多AI」
    一视同仁——它只看到 FactionSlot 和 DecisionResult。
    """

    def __init__(
        self,
        intent_parser=None,
        turn_controller=None,
        history_engine=None,
        macro_policy_engine=None,
        narrative_engine=None,
        black_swan_injector=None,
        guardrail_validator=None,
        state_applier=None,
    ):
        self.intent_parser = intent_parser
        self.turn_controller = turn_controller
        self.history_engine = history_engine
        self.macro_policy_engine = macro_policy_engine
        self.narrative_engine = narrative_engine
        self.black_swan_injector = black_swan_injector
        self.guardrail_validator = guardrail_validator
        self.state_applier = state_applier

    def resolve(
        self,
        room: GameRoom,
        world_state: WorldState,
        decisions: dict[str, DecisionResult],
        llm: LLMAdapter | None = None,
        skip_narrative: bool = False,
        guardrail_pre_state: dict | None = None,
    ) -> QuarterlyResult:
        """执行一个季度的完整模拟。

        Args:
            room: 游戏房间
            world_state: 当前世界状态（会被原地修改）
            decisions: 所有 faction 的决策 {faction_id: DecisionResult}
            llm: LLM 适配器
            skip_narrative: 流式模式下跳过第⑥步叙事生成（~22s）。状态在第⑤步
                已完全定型，叙事纯文案。跳过后把生成叙事所需的上下文（baseline /
                macro_delta / history_events / all_decisions）存入
                results.narrative_context，供 narrative-live-stream 端点稍后
                边生成边流式输出。

        Returns:
            QuarterlyResult: 包含叙事、状态变更、事件等
        """
        t_start = time.time()
        results = QuarterlyResult()

        # Snapshot the start-of-turn season so Step 7.5 can advance EXACTLY once.
        # Both the deterministic baseline (TurnController) AND the safety net used
        # to advance the season → +2/turn (seasons 春→秋→春 skipped 夏/冬). Now the
        # safety net only fires if the baseline did NOT already advance.
        _season_idx_at_start = _season_to_idx(getattr(world_state, "season", "spring"))

        # H39c: capture the season/year being PROCESSED (pre-advance). The
        # TurnController advances the season at the END of execute_turn, so by
        # the time narrative/room-sync/save run, ws.season is the NEXT season.
        # The turn record + narrative era must reflect the season the baseline
        # actually simulated, not the one it advanced into.
        _season_at_start = getattr(world_state, "season", "winter")
        _year_at_start = getattr(world_state, "year", 1644)

        # H38a: Capture BEFORE snapshots so narrative can reference actual deltas
        _before_snapshots = _snapshot_factions(world_state)

        # ── Step 1: 解析所有势力决策 ──
        all_commands: dict[str, list] = {}
        all_decisions: dict[str, str] = {}
        parse_warnings: dict[str, list] = {}  # H38c: 意图校验警告 → 回显进叙事
        for faction_id, dr in decisions.items():
            all_decisions[faction_id] = dr.decision_text
            if dr.commands:
                # AI 已预解析
                all_commands[faction_id] = dr.commands
            elif self.intent_parser:
                # 人类决策 → 优先检查预计算缓存
                parsed = None
                try:
                    from histrategy.engine.names import extract_suggestion_id
                    from histrategy.server.intent_cache import _feature_enabled
                    from histrategy.server.intent_cache import get as cache_get

                    sid = extract_suggestion_id(dr.decision_text)
                    if sid and _feature_enabled():
                        cached = cache_get(
                            sid,
                            room.id,
                            room.quarter_number,
                            faction_id,
                        )
                        if cached:
                            parsed = cached
                            logger.info(
                                "[room=%s] Intent cache HIT: sid=%s cmds=%d",
                                room.id, sid, len(parsed),
                            )
                except Exception:
                    pass

                # Cache miss or feature disabled → synchronous intent_parse
                if parsed is None:
                    _t_parse = time.time()
                    try:
                        parsed = self.intent_parser.parse(dr.decision_text, faction_id, ws=world_state)
                    except Exception as e:
                        logger.warning("[room=%s] Intent parse failed for %s: %s", room.id, faction_id, e)
                        parsed = []
                    print(f"⏱ [room={room.id}] intent_parse({faction_id}) {time.time() - _t_parse:.1f}s", flush=True)

                all_commands[faction_id] = parsed

                # H38c: 收集意图校验警告（幻影战场拦截等），稍后注入叙事回显给玩家
                _warns = getattr(self.intent_parser, "_validation_warnings", None)
                if _warns:
                    parse_warnings.setdefault(faction_id, []).extend(_warns)

        # ── Step 1.5: 从 DB 加载已有政策到 faction.policies ──
        try:
            from histrategy.db.models import get_active_policies
            for fid in world_state.factions:
                db_policies = get_active_policies(room.id, fid)
                if db_policies:
                    faction = world_state.factions[fid]
                    existing = getattr(faction, "policies", None)
                    if not isinstance(existing, dict):
                        existing = {}
                    for p in db_policies:
                        pname = p.get("policy_name", "")
                        if pname and pname not in existing:
                            existing[pname] = {
                                "type": p.get("policy_type", "law"),
                                "level": p.get("policy_level", 1),
                                "params": p.get("params", {}),
                                "status": p.get("status", "active"),
                            }
                    faction.policies = existing
        except Exception:
            pass

        # ── Step 2: 确定性基线 ──
        _log_faction_troops(world_state, "pre-baseline", room.id)
        baseline = None
        if self.turn_controller:
            try:
                baseline = self._execute_baseline(
                    world_state,
                    all_commands,
                    room,
                )
                results.baseline = baseline  # Expose for DB storage
            except Exception as e:
                logger.error("[room=%s] TurnController failed: %s", room.id, e)
                baseline = _empty_baseline(world_state)
                results.baseline = baseline
        _log_faction_troops(world_state, "post-baseline", room.id)

        # ── Step 2.5: NPC recruitment — INLINED (H36r) ──
        # Bypassing _apply_npc_structured_recruitment() entirely to rule out
        # deployment caching issues. Logic identical but directly in resolve().
        player_fid = getattr(world_state, "player_faction_id", None)
        _npc_recruited = 0
        try:
            for fid, commands in all_commands.items():
                if fid == player_fid:
                    continue
                faction = world_state.factions.get(fid)
                if not faction or not getattr(faction, "is_active", True):
                    continue
                treasury = getattr(faction, "treasury", 0) or 0
                strength = getattr(faction, "strength_actual", 0) or 0
                population = getattr(faction, "population", 0) or 0
                morale = getattr(faction, "morale_actual", 50) or 50
                faction_had_recruit = False
                for cmd in (commands or []):
                    if not isinstance(cmd, dict):
                        continue
                    ct = cmd.get("type", "")
                    params = cmd.get("params", {}) or {}
                    amt = int(params.get("amount", 0))
                    if ct == "recruit" and amt > 0:
                        amt = min(amt, int(population * 0.03))
                        cost = amt * 0.5
                        if cost > treasury:
                            amt = int(treasury / 0.5)
                            cost = amt * 0.5
                        if amt >= 50:
                            strength += amt
                            treasury -= cost
                            faction.strength_actual = strength
                            faction.treasury = treasury
                            faction_had_recruit = True
                            logger.info("H36R_INLINE %s recruit %d (cost %.0f)", fid, amt, cost)
                    elif ct == "conscript" and amt > 0:
                        amt = min(amt, int(population * 0.02))
                        cost = amt * 0.3
                        if cost > treasury:
                            amt = int(treasury / 0.3)
                            cost = amt * 0.3
                        if amt >= 50:
                            strength += amt
                            treasury -= cost
                            morale = max(0, morale - 2)
                            faction.strength_actual = strength
                            faction.treasury = treasury
                            faction.morale_actual = morale
                            faction_had_recruit = True
                            logger.info("H36R_INLINE %s conscript %d (cost %.0f)", fid, amt, cost)
                    elif ct == "disband" and amt > 0:
                        # H37c: guardrail — cap disband at 15% of current strength per quarter
                        # (same rationale as _apply_npc_structured_recruitment).
                        amt = min(amt, int(strength * 0.15), strength - 500)
                        if amt >= 50:
                            strength -= amt
                            treasury += amt * 0.2
                            population += amt
                            faction.strength_actual = strength
                            faction.treasury = treasury
                            faction.population = population
                            faction_had_recruit = True
                            # H39b: disband must ALSO reduce the deployed armies.
                            # Without this, Step 5.5 (max(deployed, reserve))
                            # reconciles strength_actual back up to the untouched
                            # army totals — the disband was silently undone
                            # (observed: 9,000 commanded → only ~1.4k net loss).
                            try:
                                from .state_applier import _reduce_army
                                _deployed = sum(
                                    a.total_troops
                                    for a in world_state.armies.values()
                                    if getattr(a, "faction_id", "") == fid and a.total_troops > 0
                                )
                                if _deployed > 0:
                                    _amt_left = amt
                                    for a in world_state.armies.values():
                                        if _amt_left <= 0:
                                            break
                                        if getattr(a, "faction_id", "") == fid and a.total_troops > 0:
                                            _share = max(1, int(amt * a.total_troops / _deployed))
                                            _share = min(_share, a.total_troops, _amt_left)
                                            _reduce_army(a, _share)
                                            _amt_left -= _share
                            except Exception as _re:
                                logger.warning(
                                    "[room=%s] disband army sync failed for %s: %s",
                                    getattr(room, "id", "?"), fid, _re,
                                )
                            logger.info("H36R_INLINE %s disband %d (+army sync H39b)", fid, amt)
                if faction_had_recruit:
                    _npc_recruited += 1
        except Exception as e:
            logger.warning("[room=%s] NPC structured recruitment failed: %s", room.id, e)
        # H37d: auto-recruit (execute_npc_recruitment) fallback REMOVED.
        # NPC recruitment now comes EXCLUSIVELY from npc_decision structured
        # commands (recruit/conscript/disband). The old deterministic auto-recruit
        # was deprecated in H36q and is no longer a fallback — if no NPC issued a
        # recruit command, that is the NPC's choice (no recruitment this turn).
        _log_faction_troops(world_state, "post-npc-recruit", room.id)

        # ── Step 2.6: Treasury starvation penalties ──
        # H35z3: Factions with 0 treasury suffer progressive morale loss,
        # desertion, and eventual collapse. Also handles food=0 starvation.
        try:
            from histrategy.engine.quarterly_engine import QuarterlyEngine as QE2
            _qe2 = QE2(scenario=getattr(room, "scenario", None))
            _qe2.execute_treasury_penalties(world_state, baseline, apply_to_player=True)
        except Exception as e:
            logger.warning("[room=%s] Treasury penalties failed: %s", room.id, e)

        # ── Step 3: 黑天鹅事件 ──
        bs_proposals = []
        if self.black_swan_injector and self.history_engine:
            try:
                from histrategy.engine.game import apply_event_effects

                proposals = self.history_engine.check_events(
                    world_state.year,
                    getattr(world_state, "season", 0),
                    world_state,
                    deviation=getattr(world_state, "player_deviation", 0.0),
                )
                for prop in proposals:
                    effects = prop.effects.get("effects", {})
                    apply_event_effects(world_state, effects)
                bs_proposals = proposals
                results.history_events = [
                    {
                        "event_id": p.event_id,
                        "title": p.title,
                        "description": p.effects.get("outcome_description", ""),
                    }
                    for p in proposals
                ]
            except Exception as e:
                logger.warning("[room=%s] BlackSwanInjector failed: %s", room.id, e)

        # ── Pre-sync: reconcile strength_actual from deployed armies ──
        # H37d-fix: the old `reserve + deployed` DOUBLE-COUNTED troops. After the
        # TurnController's periodic reconciliation, strength_actual already equals
        # deployed (armies are the source of truth), so `reserve + deployed` summed
        # the same troops twice (→ the observed +28,977 inflation). Use
        # max(deployed, reserve) so NPC recruit (which adds to strength_actual but
        # not armies) is preserved without double-counting.
        if hasattr(world_state, 'armies') and world_state.armies:
            from .state_applier import _MIN_ACTIVE_TROOPS
            for fid in world_state.factions:
                faction = world_state.factions[fid]
                deployed = sum(
                    a.total_troops for a in world_state.armies.values()
                    if getattr(a, 'faction_id', '') == fid
                )
                reserve = getattr(faction, 'strength_actual', 0) or 0
                new_total = max(deployed, reserve, _MIN_ACTIVE_TROOPS)
                if new_total and new_total != reserve:
                    faction.strength_actual = new_total

        # ── Step 4: LLM 宏观模拟 (V3 mode — runs when macro_policy_engine is available) ──
        macro_delta = {}
        if self.macro_policy_engine and llm:
            try:
                _t_macro = time.time()
                macro_delta = self._run_macro_simulation(
                    world_state,
                    all_commands,
                    all_decisions,
                    baseline,
                    bs_proposals,
                    room,
                )
                results.macro_delta = macro_delta  # Expose for DB storage
                print(f"⏱ [room={room.id}] macro_sim {time.time() - _t_macro:.1f}s", flush=True)
            except Exception as e:
                logger.error("[room=%s] MacroPolicyEngine failed: %s", room.id, e)

        # ── Step 5: Guardrail 验证 + 状态应用 ──
        if macro_delta and self.guardrail_validator:
            try:
                validation = self.guardrail_validator.validate(
                    macro_delta,
                    world_state,
                    baseline,
                )
                # validate() returns {"accepted", "violations", "warnings", "sanitized_delta"}
                if isinstance(validation, dict) and "sanitized_delta" in validation:
                    macro_delta = validation["sanitized_delta"]
                    for w in validation.get("warnings", []):
                        logger.info("[room=%s] Guardrail warning: %s", room.id, getattr(w, "message", w))
            except Exception as e:
                logger.warning("[room=%s] GuardrailValidator failed: %s", room.id, e)

        if macro_delta and self.state_applier:
            try:
                # apply_macro_delta reads the MacroPolicyEngine schema
                # (battle_results / morale_events / npc_faction_actions) and
                # mutates scalar strength_actual + faction.territories with
                # deterministic force-ratio grounding (P1/P2/P3/P4).
                applied = self.state_applier.apply_macro_delta(macro_delta, world_state, baseline)
                logger.info("[room=%s] StateApplier settled: %s", room.id, applied)
            except Exception as e:
                logger.error("[room=%s] StateApplier failed: %s", room.id, e)

        # ── Step 5.3: 从 macro_delta 提取政策并持久化到 faction.policies ──
        if macro_delta:
            _extract_policies_from_delta(macro_delta, world_state, room.id)

        # ── Step 5.6: 玩家指令校验警告回显 (H38c) ──
        # 幻影战场等被拦截的命令 → 注入叙事开头，让玩家明确知道命令为何未执行。
        # 覆盖流式（skip_narrative）与非流式路径：此处早于 Step 6 的 narrative_context 快照。
        if parse_warnings and macro_delta:
            _warn_seeds = []
            for _fid, _warns in parse_warnings.items():
                for _w in _warns:
                    _warn_seeds.append(f"⚠️ 军师来报：{_w}")
            macro_delta.setdefault("narrative_seeds", []).extend(_warn_seeds)
            if baseline is not None:
                _evts = getattr(baseline, "notable_events", None)
                if isinstance(_evts, list):
                    _evts.extend(_warn_seeds)

        # ── Step 5.5: Sync faction strength_actual from deployed army totals ──
        # H37d-fix: same double-count fix as the Pre-sync above — use
        # max(deployed, reserve), NOT reserve + deployed (which summed the same
        # troops twice and inflated strength_actual).
        if hasattr(world_state, 'armies') and world_state.armies:
            from .state_applier import _MIN_ACTIVE_TROOPS
            for fid in world_state.factions:
                faction = world_state.factions[fid]
                deployed = sum(
                    a.total_troops for a in world_state.armies.values()
                    if getattr(a, 'faction_id', '') == fid
                )
                reserve = getattr(faction, 'strength_actual', 0) or 0
                new_total = max(deployed, reserve, _MIN_ACTIVE_TROOPS)
                if new_total and new_total != reserve:
                    faction.strength_actual = new_total

        # ── Step 5.7: Guardrail clamp BEFORE narrative (H39b) ──
        # Production previously applied _clamp_extreme_changes AFTER resolve
        # returned, so the narrative (generated inside resolve) never saw the
        # clamped numbers — Q1 narrative said "粮-20,180" while the saved delta
        # was -18,000. Run the same guardrail here, before Step 6, so narrative,
        # state_changes and turn_delta all reflect the final values.
        if guardrail_pre_state is not None:
            try:
                from histrategy.server.room_manager import _clamp_extreme_changes
                _clamp_extreme_changes(world_state, guardrail_pre_state)
                logger.info(
                    "[room=%s] Guardrail clamp applied pre-narrative (H39b)",
                    getattr(room, "id", "?"),
                )
            except Exception as e:
                logger.warning(
                    "[room=%s] Guardrail pre-narrative clamp failed: %s",
                    getattr(room, "id", "?"),
                    e,
                )

        # ── Step 6: Per-faction 叙事生成 ──
        # Streaming mode: skip the ~22s narrative LLM call here and stash the
        # context so narrative-live-stream can generate + stream it afterward.
        if skip_narrative:
            results.narrative_context = {
                "all_decisions": all_decisions,
                "baseline": baseline,
                "macro_delta": macro_delta,
                "history_events": getattr(self, "_last_history_events", None),
                # H39c: the turn's PROCESSED season/year (pre-advance), so the
                # SSE narrative-live-stream regenerates with the correct era.
                "processed_year": _year_at_start,
                "processed_season": (
                    _season_at_start.value if hasattr(_season_at_start, "value") else str(_season_at_start)
                ),
            }
        elif self.narrative_engine:
            try:
                _t_narr = time.time()
                # H38a: Compute actual state deltas from before/after snapshots
                _state_deltas = _compute_state_deltas(_before_snapshots, world_state)
                results.narratives = self._generate_narratives(
                    world_state,
                    all_commands,
                    all_decisions,
                    baseline,
                    macro_delta,
                    room,
                    state_deltas=_state_deltas,
                    processed_year=_year_at_start,
                    processed_season=_season_at_start,
                )
                print(f"⏱ [room={room.id}] narrative {time.time() - _t_narr:.1f}s", flush=True)
            except Exception as e:
                logger.error("[room=%s] Narrative generation failed: %s", room.id, e)

        # ── Step 7: 状态收集 ──
        results.state_changes = _extract_state_changes(world_state, decisions)
        results.all_commands = all_commands
        results.total_latency_ms = (time.time() - t_start) * 1000

        # ── Step 7.5: 季节推进安全网（条件触发，防双重推进）──
        # TurnController.execute_turn() 正常时已推进一季；若它静默失败回退到
        # _empty_baseline()，季节不变。仅当季节仍等于回合开始时的值（说明 baseline
        # 没推进）才由安全网推进，保证净推进恰好一季。
        if _season_to_idx(getattr(world_state, "season", "spring")) == _season_idx_at_start:
            _ensure_season_advance(world_state, room.id)

        # ── Step 7.6: max_quarters 终局检查 ──
        # 本回合（quarter_number+1）达到 scenario.toml 上限时，标记 game_over。
        # 玩家可玩满 max_quarters 回合；终局后前端禁用继续推进。
        _max_q = _get_max_quarters(getattr(room, "scenario", ""))
        if _max_q > 0 and room.quarter_number + 1 >= _max_q:
            results.game_over = _build_conclusion(room, world_state)
            logger.info(
                "[room=%s] max_quarters=%d reached (quarter_number=%d) — game over",
                room.id, _max_q, room.quarter_number,
            )

        # ── Step 8: 回合摘要 ──
        results.turn_summary = _build_turn_summary(
            room,
            world_state,
            all_decisions,
            results,
        )

        # H39c: expose the processed (pre-advance) season/year for the turn
        # record — the quarter_turn row must reflect the season the baseline
        # actually simulated, not the post-advance one.
        results.processed_year = _year_at_start
        results.processed_season = (
            _season_at_start.value if hasattr(_season_at_start, "value") else str(_season_at_start)
        )

        return results

    def _execute_baseline(
        self,
        ws: WorldState,
        all_commands: dict[str, list],
        room: GameRoom,
    ):
        """执行确定性基线（TurnController multi-faction）。

        Runs execute_turn() ONCE with all faction commands combined,
        then advances season ONCE (TurnController handles the advance).
        """
        # 尝试 multi-faction 模式
        if hasattr(self.turn_controller, "execute_multi_faction_turn"):
            return self.turn_controller.execute_multi_faction_turn(
                ws,
                all_commands,
                year=ws.year,
                turn_number=ws.turn,
            )

        # 回退：合并所有 faction 的 commands，调用一次 execute_turn
        # 注意：execute_turn() 内部会 _advance_season，所以这里只需调用一次
        combined_commands = []
        for faction_id, commands in all_commands.items():
            for cmd in commands:
                # Inject faction_id if missing (dict form)
                if isinstance(cmd, dict) and "faction_id" not in cmd:
                    cmd = {**cmd, "faction_id": faction_id}
                combined_commands.append(cmd)

        try:
            return self.turn_controller.execute_turn(
                ws,
                player_commands=combined_commands,
                year=ws.year,
                turn_number=getattr(ws, "turn_number", getattr(ws, "turn", 1)),
            )
        except Exception as e:
            logger.exception("[room=%s] Baseline execution failed: %s", getattr(room, "id", "?"), e)
        return _empty_baseline(ws)

    def _run_macro_simulation(
        self,
        ws,
        all_commands,
        all_decisions,
        baseline,
        bs_proposals,
        room,
    ) -> dict:
        """运行 LLM 宏观模拟。"""
        # 构建玩家策令文本（主要faction的决策）
        player_faction = None
        for slot in room.active_slots():
            if slot.is_human():
                player_faction = slot.faction_id
                break
        if not player_faction:
            player_faction = next(iter(all_decisions.keys()), None)

        player_decision = all_decisions.get(player_faction, "")
        player_commands = all_commands.get(player_faction, [])

        # NPC 行动（非玩家 faction）
        npc_actions = []
        for fid, decision in all_decisions.items():
            if fid != player_faction:
                npc_actions.append(
                    {
                        "faction": fid,
                        "action": decision,
                    }
                )

        # Load active policies for all factions to inject as epoch_memory
        epoch_memory = []
        try:
            from histrategy.db.models import get_active_policies
            for fid in all_decisions:
                policies = get_active_policies(room.id, fid)
                for p in policies:
                    pname = p.get("policy_name", "")
                    ptype = p.get("policy_type", "law")
                    epoch_memory.append({
                        "note": f"[{fid}] [{ptype}] {pname}: level={p.get('policy_level',1)}, "
                                f"status={p.get('status','active')}, params={p.get('params',{})}"
                    })
        except Exception:
            pass

        return self.macro_policy_engine.simulate(
                ws,
                policy_commands=player_commands,
                player_decision=player_decision,
                baseline=baseline or _empty_baseline(ws),
                history_events=[{"event_id": p.event_id, "title": p.title} for p in bs_proposals]
                if bs_proposals
                else [],
                turn_memory=room.turn_summaries[-8:] if room.turn_summaries else [],
                epoch_memory=epoch_memory,
                room_id=room.id,
                quarter_number=room.quarter_number + 1,
            )

    def _generate_narratives(
        self,
        ws,
        all_commands,
        all_decisions,
        baseline,
        macro_delta,
        room,
        state_deltas: dict | None = None,
        processed_year: int | None = None,
        processed_season=None,
    ) -> dict[str, str]:
        """Generate a single global narrative covering all factions.

        Replaces the old per-faction ThreadPoolExecutor approach with ONE LLM call.
        All factions receive the same global narrative (with backward-compat dict keys).
        """
        narratives: dict[str, str] = {}
        factions = list(all_decisions.keys())
        if not factions or not self.narrative_engine:
            return narratives

        global_narrative = self.narrative_engine.generate_global_narrative(
            ws=ws,
            faction_decisions=all_decisions,
            baseline=baseline,
            macro_delta=macro_delta,
            history_events=getattr(self, "_last_history_events", None),
            room_id=room.id,
            scenario=getattr(room, "scenario", ""),
            state_deltas=state_deltas,
            year=processed_year,
            season=processed_season,
        )

        if not global_narrative or not global_narrative.strip():
            global_narrative = self.narrative_engine._offline_global_narrative(ws, all_decisions)

        # Store under "global" key + backward-compat per-faction keys
        narratives["global"] = global_narrative
        for fid in factions:
            narratives[fid] = global_narrative

        return narratives


# ── Result Data Class ──────────────────────────────


class QuarterlyResult:
    """季度模拟的完整结果。"""

    __slots__ = (
        "narratives",
        "state_changes",
        "history_events",
        "total_latency_ms",
        "turn_summary",
        "game_over",
        "narrative_context",
        "all_commands",
        "baseline",
        "macro_delta",
        "processed_year",
        "processed_season",
    )

    def __init__(self):
        self.narratives: dict[str, str] = {}  # faction_id → 叙事文本
        self.state_changes: dict[str, dict] = {}  # faction_id → 资源变化
        self.history_events: list[dict] = []
        self.total_latency_ms: float = 0
        self.turn_summary: dict = {}
        self.game_over: dict | None = None
        # Set only in streaming mode (skip_narrative=True): stashed inputs for
        # deferred narrative generation by narrative-live-stream.
        self.narrative_context: dict | None = None
        self.baseline = None  # TurnResult from deterministic simulation
        self.macro_delta: dict = {}  # LLM macro simulation delta
        self.processed_year: int | None = None  # H39c: pre-advance year
        self.processed_season: str | None = None  # H39c: pre-advance season


# ── Helpers ────────────────────────────────────────


def _extract_policies_from_delta(macro_delta: dict, world_state, room_id: str) -> None:
    """Extract policy declarations from macro simulation delta.

    Converts political_events and diplomatic npc_faction_actions into
    structured policy entries on each faction. These are then saved to
    the policy_state table by _save_v3_state_to_db.

    Policy types matched:
    - court_intrigue → law (e.g. "马士英党争", "史可法被参")
    - reform_feedback → law (e.g. "税制改革", "减田赋")
    - diplomacy actions → diplomacy (e.g. "结盟", "缔和")
    - tax actions → economic (e.g. "加征商税", "减税")
    - conscript actions → military (e.g. "大征兵", "募乡勇")
    """
    political_events = macro_delta.get("political_events", []) or []
    npc_actions = macro_delta.get("npc_faction_actions", []) or []

    # Track which policies we've already set to avoid duplicates
    seen = {}  # (faction, policy_type, policy_name) → True

    for event in political_events:
        fid = event.get("faction", "")
        event_type = event.get("type", "")
        desc = event.get("description", "")
        effects = event.get("effects", {})

        if not fid or fid not in world_state.factions:
            continue

        faction = world_state.factions[fid]
        policies = getattr(faction, "policies", None)
        if not isinstance(policies, dict):
            faction.policies = {}
            policies = faction.policies

        # Map event types to policy names
        policy_name = None
        policy_type = "law"

        if event_type == "court_intrigue":
            policy_name = "朝堂党争"
            policy_type = "law"
        elif event_type == "reform_feedback":
            policy_name = "政制改革"
            policy_type = "law"
        elif event_type == "factionalism":
            policy_name = "派系斗争"
            policy_type = "law"
        elif event_type == "succession":
            policy_name = "继嗣之争"
            policy_type = "law"

        if policy_name and (fid, policy_type, policy_name) not in seen:
            seen[(fid, policy_type, policy_name)] = True
            policies[policy_name] = {
                "type": policy_type,
                "level": 1,
                "params": {"description": desc[:200], "effects": effects},
                "status": "active",
            }

    for action in npc_actions:
        fid = action.get("faction", "")
        action_type = action.get("action_type", "")
        target = action.get("target", "")
        reason = action.get("reason", "")

        if not fid or fid not in world_state.factions:
            continue

        faction = world_state.factions[fid]
        policies = getattr(faction, "policies", None)
        if not isinstance(policies, dict):
            faction.policies = {}
            policies = faction.policies

        policy_name = None
        policy_type = "law"

        if action_type == "diplomacy" and target:
            policy_name = f"外交_{target}"
            policy_type = "diplomacy"
        elif action_type == "tax":
            policy_name = "税制调整"
            policy_type = "economic"
        elif action_type == "conscript":
            policy_name = "征兵令"
            policy_type = "military"
        elif action_type == "develop":
            policy_name = "发展令"
            policy_type = "economic"
        elif action_type == "declare_war" and target:
            policy_name = f"征伐_{target}"
            policy_type = "military"
        elif action_type == "trade" and target:
            # Import weapons / technology trade
            goods = action.get("goods", "")
            if "炮" in goods or "cannon" in goods:
                policy_name = "进口火炮"
                policy_type = "military"
            elif "枪" in goods or "火器" in goods or "arquebus" in goods:
                policy_name = "进口火器"
                policy_type = "military"
            else:
                policy_name = f"贸易_{target}"
                policy_type = "economic"

        if policy_name and (fid, policy_type, policy_name) not in seen:
            seen[(fid, policy_type, policy_name)] = True
            policies[policy_name] = {
                "type": policy_type,
                "level": 1,
                "params": {"reason": reason[:200], "target": target},
                "status": "active",
            }


def _empty_baseline(ws: WorldState):
    """创建一个空的基线结果（当 TurnController 不可用时）。"""
    from types import SimpleNamespace

    return SimpleNamespace(
        battles=[],
        resource_changes={},
        character_events=[],
        history_events=[],
        notable_events=[],
        season_name=str(getattr(getattr(ws, "season", None), "cn", None) or getattr(ws, "season", "?")),
        year=ws.year,
        tax_revenue={},
        food_delta={},
        population_delta={},
        morale_delta={},
    )


_SEASON_ORDER = ["spring", "summer", "autumn", "winter"]
_CN_SEASON_TO_EN = {"春": "spring", "夏": "summer", "秋": "autumn", "冬": "winter"}


def _season_to_idx(season) -> int:
    """Normalize a season (Season enum / '春' / 'spring') to index 0-3.

    Mirrors the normalization in _ensure_season_advance so callers can compare
    the season before/after resolution without duplicating enum handling.
    """
    if hasattr(season, "value") and isinstance(season.value, str):
        s = season.value
    elif hasattr(season, "cn") and isinstance(season.cn, str):
        s = season.cn
    else:
        s = str(season)
    s = str(s).lower()
    s = _CN_SEASON_TO_EN.get(s, s)
    return _SEASON_ORDER.index(s) if s in _SEASON_ORDER else 0


def _ensure_season_advance(ws: WorldState, room_id: str = "?") -> None:
    """安全网：无条件推进一季，防止 TurnController 静默失败导致季节卡住。

    同时支持 Season enum 和字符串 season（反序列化后可能是字符串）。
    """
    try:
        from histrategy_engine.world import Season

        # 支持 Season enum 和字符串
        _SEASON_ORDER = ["spring", "summer", "autumn", "winter"]
        _SEASON_ENUM_MAP = {
            "spring": Season.SPRING,
            "summer": Season.SUMMER,
            "autumn": Season.AUTUMN,
            "winter": Season.WINTER,
        }

        current = ws.season
        # 规范化当前 season 为字符串
        if hasattr(current, "value"):
            current_str = current.value
        elif hasattr(current, "cn"):
            # Season enum 有 .cn 属性
            current_str = current.cn if current.cn in ("春", "夏", "秋", "冬") else _SEASON_ORDER[0]
            # 中文 → 英文映射
            _CN_TO_EN = {"春": "spring", "夏": "summer", "秋": "autumn", "冬": "winter"}
            current_str = _CN_TO_EN.get(current_str, current_str)
        else:
            current_str = str(current).lower()

        if current_str not in _SEASON_ORDER:
            logger.warning("[room=%s] Unknown season '%s', defaulting to spring", room_id, current_str)
            current_str = "spring"

        idx = _SEASON_ORDER.index(current_str)
        next_idx = (idx + 1) % 4
        next_str = _SEASON_ORDER[next_idx]

        # 设置新 season（优先使用 Season enum）
        ws.season = _SEASON_ENUM_MAP.get(next_str, next_str)

        if next_idx == 0:
            ws.year += 1
        ws.turn_number = getattr(ws, "turn_number", 0) + 1
        logger.info(
            "[room=%s] Season advanced: %s → %s (year=%s, turn=%s)",
            room_id,
            current_str,
            next_str,
            ws.year,
            ws.turn_number,
        )
    except Exception as e:
        logger.error("[room=%s] Season advance failed: %s", room_id, e)


def _log_exc(room_id: str, context: str, exc: Exception) -> None:
    """结构化异常日志：统一前缀 [room=X]，方便 grep/日志平台过滤。"""
    logger.error("[room=%s] %s: %s", room_id, context, exc)


def _resolve_territory_name(tid: str) -> str:
    """Resolve a territory ID to its Chinese display name. Falls back to tid."""
    try:
        from histrategy.engine.names import _TERRITORY_ZH
        return _TERRITORY_ZH.get(tid, tid)
    except ImportError:
        return tid


def _extract_state_changes(
    ws: WorldState,
    decisions: dict[str, DecisionResult],
) -> dict[str, dict]:
    """Extract state change summaries for ALL active factions.

    Bug H35d fix: previously only iterated over factions in the decisions dict,
    which excluded NPC factions that didn't submit explicit decisions. Now
    iterates over ALL active factions in the WorldState so NPCs always show
    their actual strength/morale/food/treasury in the API response.

    Bug H35f fix: territory population is computed from faction.territories
    → ws.territories[id].population rather than relying on territory.owner_id
    (which is frequently empty after deserialization). Falls back to
    faction.population or a per-territory estimate (50000).
    """
    changes = {}
    # Build territory ownership map: {faction_id: [territory_ids]}
    faction_territories: dict[str, list[str]] = {}
    faction_populations: dict[str, int] = {}
    for tid, territory in ws.territories.items():
        owner = getattr(territory, "owner_id", "") or ""
        if owner and owner in ws.factions:
            faction_territories.setdefault(owner, []).append(tid)
            faction_populations[owner] = faction_populations.get(owner, 0) + getattr(territory, "population", 0)
    for faction_id, faction in ws.factions.items():
        if not faction.is_active:
            continue
        owned = faction_territories.get(faction_id, [])
        # Also check faction.territories as fallback
        if not owned:
            owned = list(faction.territories) if getattr(faction, "territories", None) else []
        # Compute population: faction.population is the DYNAMIC value
        # (updated by quarterly engine as tax/battles/season change), while
        # ws.territories[].population is static scenario data. H39: use
        # faction.population FIRST (matches build_faction_status_for_api),
        # territory sum only as fallback for legacy V1 factions that never
        # populate the field.
        pop = getattr(faction, "population", 0) or 0
        if not pop and owned:
            pop = sum(
                getattr(ws.territories.get(tid), "population", 0) or 0
                for tid in owned
            )
        if not pop:
            pop = faction_populations.get(faction_id, 0)
        if not pop:
            pop = max(100, len(owned) * 50000)
        changes[faction_id] = {
            "strength": getattr(faction, "strength_actual", 0),
            "treasury": faction.treasury,
            "food": faction.food,
            "morale": getattr(faction, "morale_actual", 50),
            "territories": owned,
            "population": pop,
            "is_active": faction.is_active,
        }
    # Add faction_stats summary
    faction_stats = {}
    for faction_id, faction in ws.factions.items():
        if not faction.is_active:
            continue
        owned = faction_territories.get(faction_id, [])
        if not owned:
            owned = list(faction.territories) if getattr(faction, "territories", None) else []
        pop = getattr(faction, "population", 0) or 0
        if not pop and owned:
            pop = sum(
                getattr(ws.territories.get(tid), "population", 0) or 0
                for tid in owned
            )
        if not pop:
            pop = faction_populations.get(faction_id, 0)
        if not pop:
            pop = max(100, len(owned) * 50000)
        faction_stats[faction_id] = {
            "population": pop,
            "troops": getattr(faction, "strength_actual", 0),
            "food": getattr(faction, "food", 0),
            "treasury": getattr(faction, "treasury", 0),
            "morale": getattr(faction, "morale_actual", 50),
            "territories": len(owned),
            "territory_names": [_resolve_territory_name(tid) for tid in owned],
        }
    changes["faction_stats"] = faction_stats
    return changes


def _build_turn_summary(
    room: GameRoom,
    ws: WorldState,
    all_decisions: dict[str, str],
    results: QuarterlyResult,
) -> dict:
    """构建回合摘要（用于后续 LLM 上下文）。

    Previously truncated decisions to 60 chars, losing 90% of information.
    Now uses 300-char limits and includes narrative fragments for richer context.
    """
    season_cn = ws.current_season_cn
    decision_summaries = []
    for fid, decision in all_decisions.items():
        # Keep up to 300 chars — long enough to preserve strategic intent
        short = decision[:300] + "..." if len(decision) > 300 else decision
        faction = ws.factions.get(fid)
        name = faction.name if faction else fid
        decision_summaries.append(f"{name}: {short}")

    # Include narrative fragments in the summary
    narrative_fragments = []
    if results.narratives:
        for fid, narrative in list(results.narratives.items())[:3]:
            # Take first 120 chars of each narrative as context
            fragment = narrative[:120] + "..." if len(narrative) > 120 else narrative
            faction = ws.factions.get(fid)
            name = faction.name if faction else fid
            narrative_fragments.append(f"{name}叙事: {fragment}")

    narrative_str = " | ".join(narrative_fragments) if narrative_fragments else ""

    events_str = (
        "; ".join(e.get("title", "") for e in results.history_events[:4]) if results.history_events else "天下无事"
    )

    # Build rich outcome_summary with decisions + narratives + events
    decisions_str = " | ".join(decision_summaries[:4])  # all factions, not just 3
    parts = [f"[{ws.year}年{season_cn}]", decisions_str]
    if narrative_str:
        parts.append(narrative_str)
    parts.append(f"→ {events_str}")

    return {
        "outcome_summary": " ".join(parts),
        "turn": ws.turn,
        "year": ws.year,
        "season": season_cn,
    }


# ── H38a: Before/after state delta helpers ──

def _snapshot_factions(ws: WorldState) -> dict[str, dict]:
    """Capture pre-turn snapshot of all active factions."""
    snap: dict[str, dict] = {}
    # Build territory ownership map from ws.territories
    faction_terrs: dict[str, list[str]] = {}
    if hasattr(ws, "territories") and ws.territories:
        for tid, t in ws.territories.items():
            owner = getattr(t, "owner_id", "") or ""
            if owner and owner in ws.factions:
                faction_terrs.setdefault(owner, []).append(tid)
    for fid, faction in ws.factions.items():
        if not getattr(faction, "is_active", True):
            continue
        terrs = faction_terrs.get(fid, [])
        if not terrs:
            terrs = list(getattr(faction, "territories", []) or [])
        snap[fid] = {
            "troops": getattr(faction, "strength_actual", 0) or 0,
            "food": getattr(faction, "food", 0) or 0,
            "treasury": getattr(faction, "treasury", 0) or 0,
            "morale": getattr(faction, "morale_actual", 50) or 50,
            "population": getattr(faction, "population", 0) or 0,
            "territory_ids": terrs,
        }
    return snap


def _compute_state_deltas(
    before: dict[str, dict],
    ws: WorldState,
) -> dict[str, list[dict]]:
    """Compute per-faction state deltas from before/after snapshots."""
    deltas: dict[str, list[dict]] = {}
    for fid, prev in before.items():
        faction = ws.factions.get(fid)
        if not faction or not getattr(faction, "is_active", True):
            continue
        curr = {
            "troops": getattr(faction, "strength_actual", 0) or 0,
            "food": getattr(faction, "food", 0) or 0,
            "treasury": getattr(faction, "treasury", 0) or 0,
            "morale": getattr(faction, "morale_actual", 50) or 50,
            "population": getattr(faction, "population", 0) or 0,
        }
        # H38d: Include territory changes to prevent narrative hallucination
        curr_terrs = []
        if hasattr(ws, "territories") and ws.territories:
            for tid, t in ws.territories.items():
                if getattr(t, "owner_id", "") == fid:
                    curr_terrs.append(tid)
        if not curr_terrs:
            curr_terrs = list(getattr(faction, "territories", []) or [])
        prev_terrs = prev.get("territory_ids", [])
        gained = [tid for tid in curr_terrs if tid not in prev_terrs]
        lost = [tid for tid in prev_terrs if tid not in curr_terrs]

        changes = []
        for key, label in [("troops", "troops"), ("food", "food"), ("treasury", "treasury"), ("morale", "morale"), ("population", "population")]:
            old_v = prev.get(key, 0) or 0
            new_v = curr.get(key, 0) or 0
            delta = new_v - old_v
            changes.append({
                "delta_type": label,
                "old_value": old_v,
                "new_value": new_v,
                "delta": delta,
            })
        if gained:
            changes.append({"delta_type": "territory_gained", "old_value": 0, "new_value": len(gained), "delta": len(gained), "detail": gained})
        if lost:
            changes.append({"delta_type": "territory_lost", "old_value": 0, "new_value": len(lost), "delta": -len(lost), "detail": lost})
        deltas[fid] = changes
    return deltas
