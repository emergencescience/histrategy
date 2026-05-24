"""GameLogExporter — export session logs for community contribution.

Players can share their alternate history playthroughs via structured
JSON logs. These logs are also the raw data for academic analysis.

Usage:
    exporter = GameLogExporter(faction_id="cao_cao")
    exporter.record_turn(turn_context, sim_result)
    exporter.save()  # writes to ~/.histrategy/logs/

CLI:
    histrategy --export-log   # saves current session log
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

LOG_SCHEMA_VERSION = "0.3"


def _log_dir() -> Path:
    override = os.environ.get("HISTRATEGY_DATA_DIR")
    base = Path(override).expanduser() if override else Path.home() / ".histrategy"
    return base / "logs"


@dataclass
class TurnLog:
    """Record of a single game turn."""
    turn: int
    year: int
    season: str
    player_decision: str
    advisor_speeches: list[dict] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    consequences: dict = field(default_factory=dict)   # state_changes
    seeds: list[dict] = field(default_factory=list)
    npc_reactions: list[str] = field(default_factory=list)
    aftermath: str = ""
    deviation_score: float = 0.0
    engine_used: str = ""


@dataclass
class GameLog:
    """Complete session log — one per game."""
    schema_version: str = LOG_SCHEMA_VERSION
    faction_id: str = ""
    faction_name: str = ""
    player_id: str = "anonymous"      # opt-in attribution
    started_at: str = ""
    ended_at: str = ""
    outcome: str = ""                  # "victory" | "defeat" | "abandoned"
    final_score: str = ""
    turns: list[TurnLog] = field(default_factory=list)
    total_turns: int = 0
    final_deviation: float = 0.0


class GameLogExporter:
    """Records and exports game session logs.

    Logs are saved to ~/.histrategy/logs/YYYY-MM-DD-{faction}.json.
    """

    def __init__(self, faction_id: str, faction_name: str = "") -> None:
        self._log = GameLog(
            faction_id=faction_id,
            faction_name=faction_name,
            started_at=datetime.now().isoformat(),
        )

    def record_turn(
        self,
        turn: int,
        year: int,
        season: str,
        player_decision: str,
        sim_result,          # SimResult object
        advisor_speeches: list[dict] | None = None,
        suggestions: list[str] | None = None,
        deviation: float = 0.0,
    ) -> None:
        """Record one turn of gameplay."""
        entry = TurnLog(
            turn=turn,
            year=year,
            season=season,
            player_decision=player_decision,
            advisor_speeches=advisor_speeches or [],
            suggestions=suggestions or [],
            consequences=getattr(sim_result, "state_changes", {}),
            seeds=getattr(sim_result, "seeds", []),
            npc_reactions=getattr(sim_result, "npc_reactions", []),
            aftermath=getattr(sim_result, "aftermath", ""),
            deviation_score=deviation,
            engine_used=getattr(sim_result, "engine_id", ""),
        )
        self._log.turns.append(entry)

    def finish(
        self,
        outcome: str = "abandoned",
        final_score: str = "",
        final_deviation: float = 0.0,
    ) -> None:
        """Finalize the log at game end."""
        self._log.ended_at = datetime.now().isoformat()
        self._log.outcome = outcome
        self._log.final_score = final_score
        self._log.total_turns = len(self._log.turns)
        self._log.final_deviation = final_deviation

    def save(self) -> Path:
        """Save log to disk. Returns the saved file path."""
        log_dir = _log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"{date_str}-{self._log.faction_id}.json"
        path = log_dir / filename

        data = asdict(self._log)
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return path

    def to_markdown(self) -> str:
        """Generate a human-readable Markdown summary of the session."""
        log = self._log
        lines = [
            f"# 《三國志略》游戏记录",
            f"**势力**: {log.faction_name} | **结局**: {log.outcome}",
            f"**回合数**: {log.total_turns} | **历史偏差**: {log.final_deviation:.2f}",
            f"**最终评分**: {log.final_score}",
            "",
        ]
        for t in log.turns:
            lines.append(f"## 第{t.turn}回合 · {t.year}年{t.season}")
            lines.append(f"> 决策: {t.player_decision}")
            if t.aftermath:
                lines.append(f"\n{t.aftermath}")
            lines.append("")
        return "\n".join(lines)
