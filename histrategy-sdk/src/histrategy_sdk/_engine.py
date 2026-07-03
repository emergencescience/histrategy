"""DirectEngine — in-process game engine wrapper.

Use this when you have histrategy-engine installed locally.
No server needed — the game runs in your Python process.

Requires: pip install histrategy-sdk[engine]
"""

from __future__ import annotations

from .exceptions import EngineNotAvailableError, TurnExecutionError
from .types import FactionStatus, GameIntro, PlanData, TurnResult


class DirectEngine:
    """In-process game engine for 三國志略.

    Usage:
        engine = DirectEngine(faction="shu")
        intro = engine.get_intro()
        plan = engine.get_plan()
        result = engine.execute("联吴抗曹，攻打襄阳")
        print(result["narrative"])

        # Save and restore
        data = engine.to_dict()
        engine2 = DirectEngine.from_dict(data)
    """

    def __init__(
        self,
        scenario: str = "three-kingdoms",
        faction: str = "shu",
        llm_api_key: str | None = None,
        llm_provider: str | None = None,
        lang: str = "zh",
    ):
        """Create a new game engine.

        Args:
            scenario: Scenario ID ("three-kingdoms")
            faction: Player faction ("shu", "cao", "wu")
            llm_api_key: API key for LLM provider (auto-detected if unset)
            llm_provider: Override provider detection ("deepseek", "openai", "tongyi")
            lang: Language for narratives and NPC decisions ("zh" or "en")
        """
        self._ensure_engine_available()

        import os as _os

        if llm_api_key:
            _os.environ["DEEPSEEK_API_KEY"] = llm_api_key

        from histrategy.engine.game import GameEngine
        from histrategy.llm.adapter import LLMAdapter

        try:
            llm = LLMAdapter(provider=llm_provider or None)
        except Exception:
            llm = None

        self._engine = GameEngine(scenario=scenario, new_game=True, llm=llm)
        self._engine.set_player_faction(faction)
        # Override scenario language (e.g. "en" for English narratives)
        if lang and lang in ("zh", "en"):
            self._engine._scenario_language = lang
            # Re-initialize NarrativeEngine with correct language
            if hasattr(self._engine, "narrative_engine") and self._engine.narrative_engine:
                from histrategy.llm.narrative import NarrativeEngine

                scenario = getattr(self._engine, "scenario", "") or getattr(self._engine, "_scenario", "")
                self._engine.narrative_engine = NarrativeEngine(llm, language=lang, scenario=scenario)
        self._game_id = self._engine.world_state_v2.player_faction_id if self._engine._use_v2 else "local"

    @staticmethod
    def _ensure_engine_available() -> None:
        try:
            import histrategy.engine.game  # noqa: F401
        except ImportError:
            raise EngineNotAvailableError(
                "DirectEngine requires the full histrategy package.\n"
                "Install with: pip install histrategy-sdk[engine]\n"
                "Or use ServerClient for remote games."
            ) from None

    # ── Properties ────────────────────────────────────────

    @property
    def game_id(self) -> str:
        return self._game_id

    # ── Game API ──────────────────────────────────────────

    def get_intro(self) -> GameIntro:
        """Get the game intro scene.

        Returns:
            GameIntro with narrative, suggestions, faction_status.
        """
        from histrategy.engine.game import _suppress_stderr

        with _suppress_stderr():
            intro = self._engine.get_intro_scene()

        ws = self._engine.world_state_v2

        narrative = ""
        suggestions: list[str] = []
        if isinstance(intro, dict):
            narrative = intro.get("narrative", "")
            suggestions = intro.get("new_choices", [])
        elif isinstance(intro, str):
            narrative = intro

        return GameIntro(
            game_id=self._game_id,
            scenario=self._engine.scenario,
            faction=ws.player_faction_id,
            narrative=narrative,
            suggestions=suggestions,
            faction_status=self._get_status_inner(),
        )

    def get_plan(self) -> PlanData:
        """Get Plan Mode: advisor court dialogue + strategic suggestions.

        Returns:
            PlanData with court_dialogue, suggestions, faction_status.
        """
        from histrategy.engine.game import _suppress_stderr

        with _suppress_stderr():
            plan = self._engine.get_plan_data()

        status = self._get_status_inner()

        return PlanData(
            game_id=self._game_id,
            court_dialogue=plan.get("court_dialogue", ""),
            suggestions=plan.get("suggestions", []),
            season_summary=plan.get("season_summary", ""),
            year=status.get("year", 207),
            season=status.get("season", "春"),
            turn=status.get("turn", 1),
            faction_status=status,
        )

    def execute(self, decision: str) -> TurnResult:
        """Submit a player decision and process the turn.

        Args:
            decision: Free-text player decision (e.g. "联吴抗曹，攻打襄阳")

        Returns:
            TurnResult with narrative, aftermath, state_changes, suggestions.
        """
        from histrategy.engine.game import _suppress_stderr

        try:
            with _suppress_stderr():
                result = self._engine.process_turn(decision)
        except Exception as e:
            raise TurnExecutionError(f"Turn execution failed: {e}") from e

        status = self._get_status_inner()

        usage = result.get("_usage", {})
        from .types import TokenUsage

        return TurnResult(
            game_id=self._game_id,
            narrative=result.get("narrative", ""),
            aftermath=result.get("aftermath", ""),
            state_changes=result.get("state_changes", {}),
            events_occurred=result.get("events_occurred", []),
            npc_actions=result.get("npc_actions", result.get("npc_reactions", [])),
            new_suggestions=result.get("new_choices", []),
            game_over=result.get("game_over"),
            faction_status=status,
            year=status.get("year", 207),
            season=status.get("season", "春"),
            turn=status.get("turn", 1),
            token_usage=TokenUsage(
                command_tokens=usage.get("command_tokens", 0),
                plan_tokens=usage.get("plan_tokens", 0),
                npc_tokens=usage.get("npc_tokens", 0),
                sim_tokens=usage.get("sim_tokens", 0),
            ),
        )

    def get_status(self) -> FactionStatus:
        """Get current faction status."""
        return self._get_status_inner()

    def to_dict(self) -> dict:
        """Serialize the full game state to a JSON-safe dict.

        Use with from_dict() to save and restore games.
        """
        return self._engine.to_dict()

    @classmethod
    def from_dict(
        cls,
        data: dict,
        llm_api_key: str | None = None,
        llm_provider: str | None = None,
        lang: str = "zh",
    ) -> DirectEngine:
        """Restore a game from a previously saved world_state dict.

        Args:
            data: Full world_state dict (from to_dict())
            llm_api_key: API key for LLM provider
            llm_provider: Override provider detection
            lang: Language for narratives ("zh" or "en")

        Returns:
            DirectEngine with restored game state.
        """
        cls._ensure_engine_available()

        import os as _os

        if llm_api_key:
            _os.environ["DEEPSEEK_API_KEY"] = llm_api_key

        from histrategy.engine.game import GameEngine
        from histrategy.llm.adapter import LLMAdapter

        try:
            llm = LLMAdapter(provider=llm_provider or None)
        except Exception:
            llm = None

        engine = GameEngine.from_dict(data, llm=llm)
        if lang and lang in ("zh", "en"):
            engine._scenario_language = lang
            # Re-initialize NarrativeEngine with correct language
            from histrategy.llm.narrative import NarrativeEngine

            if hasattr(engine, "narrative_engine"):
                scenario = getattr(engine, "scenario", "")
                engine.narrative_engine = NarrativeEngine(llm, language=lang, scenario=scenario)
        instance = cls.__new__(cls)
        instance._engine = engine
        instance._game_id = engine.world_state_v2.player_faction_id
        return instance

    # ── Internal ──────────────────────────────────────────

    def _get_status_inner(self) -> FactionStatus:
        """Extract faction status from the engine (mirrors server api.py)."""
        ws = self._engine.world_state_v2
        player = ws.factions.get(ws.player_faction_id)
        if not player:
            return FactionStatus(
                name="?",
                faction_id="?",
                strength=0,
                food=0,
                treasury=0,
                territories=[],
                territory_names=[],
                morale=0,
                is_active=False,
                year=ws.year,
                season=ws.season.cn if hasattr(ws.season, "cn") else ws.season.value,
                turn=ws.turn_number,
            )

        # Resolve territory names
        territory_names = []
        for tid in player.territories:
            t = ws.territories.get(tid)
            territory_names.append(t.name if t else tid)

        return FactionStatus(
            name=player.name,
            faction_id=ws.player_faction_id,
            strength=player.strength_actual,
            food=player.food,
            treasury=player.treasury,
            territories=list(player.territories),
            territory_names=territory_names,
            morale=player.morale_actual,
            is_active=player.is_active,
            year=ws.year,
            season=ws.season.cn if hasattr(ws.season, "cn") else ws.season.value,
            turn=ws.turn_number,
        )
