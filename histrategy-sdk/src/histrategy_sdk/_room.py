"""Room — file-based game state container.

Every turn reads world_state from disk, executes, and writes back.
Designed for AI agents that reset context daily — state survives
entirely in ~/.histrategy/rooms/<name>/ on the filesystem.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ._engine import DirectEngine
from .types import FactionStatus, GameIntro, PlanData, TurnResult


def _rooms_dir() -> Path:
    base = os.environ.get("HISTRATEGY_DATA_DIR", os.path.expanduser("~/.histrategy"))
    return Path(base) / "rooms"


@dataclass
class Room:
    """A persistent game room backed by files in ~/.histrategy/rooms/<name>/.

    Every play() call:
      1. Loads world_state.json from disk
      2. Rebuilds the engine via DirectEngine.from_dict()
      3. Executes the player's decision
      4. Writes world_state.json back to disk
      5. Appends the turn result to turns.jsonl

    No in-memory state between calls — perfect for agents that reset daily.
    """

    name: str
    faction: str
    room_dir: Path
    created_at: str
    _engine: DirectEngine | None = field(default=None, repr=False)

    # ── Factory methods ────────────────────────────────────────

    @classmethod
    def create(
        cls,
        name: str,
        *,
        faction: str = "shu",
        scenario: str = "207",
        llm_api_key: str | None = None,
        llm_provider: str | None = None,
    ) -> Room:
        """Create a new game room.

        Args:
            name: Room name (e.g. "my-campaign" or "group-chat-42/shu")
            faction: "shu" (刘备), "cao" (曹操), or "wu" (孙权)
            scenario: Scenario ID, currently only "207"
            llm_api_key: API key for LLM (auto-detected from env if unset)
            llm_provider: "deepseek", "openai", "tongyi" (auto-detected)

        Returns:
            Room with engine initialized and initial state saved to disk.

        Raises:
            FileExistsError: If room already exists.
        """
        room_dir = _rooms_dir() / name
        if room_dir.exists():
            raise FileExistsError(f"Room '{name}' already exists at {room_dir}")

        room_dir.mkdir(parents=True, exist_ok=False)

        engine = DirectEngine(
            scenario=scenario,
            faction=faction,
            llm_api_key=llm_api_key,
            llm_provider=llm_provider,
        )

        room = cls(
            name=name,
            faction=faction,
            room_dir=room_dir,
            created_at=datetime.now(timezone.utc).isoformat(),
            _engine=engine,
        )
        room._save()
        room._write_metadata()
        return room

    @classmethod
    def load(
        cls,
        name: str,
        *,
        llm_api_key: str | None = None,
        llm_provider: str | None = None,
    ) -> Room:
        """Load an existing room from disk.

        Args:
            name: Room name (same as used in create())
            llm_api_key: API key for LLM (auto-detected if unset)
            llm_provider: Override provider

        Returns:
            Room with engine restored from saved world_state.

        Raises:
            FileNotFoundError: If room doesn't exist.
        """
        room_dir = _rooms_dir() / name
        if not room_dir.is_dir():
            raise FileNotFoundError(f"Room '{name}' not found at {room_dir}")

        state_path = room_dir / "world_state.json"
        if not state_path.exists():
            raise FileNotFoundError(f"No world_state.json in room '{name}'")

        with open(state_path) as f:
            world_state = json.load(f)

        meta_path = room_dir / "metadata.json"
        metadata = {}
        if meta_path.exists():
            with open(meta_path) as f:
                metadata = json.load(f)

        engine = DirectEngine.from_dict(
            world_state,
            llm_api_key=llm_api_key,
            llm_provider=llm_provider,
        )

        return cls(
            name=name,
            faction=metadata.get("faction", world_state.get("player_faction_id", "?")),
            room_dir=room_dir,
            created_at=metadata.get("created_at", ""),
            _engine=engine,
        )

    # ── Game API ───────────────────────────────────────────────

    def play(self, decision: str) -> TurnResult:
        """Execute a turn and persist immediately to disk.

        This is the main entry point for AI agents. Each call:
          1. Ensures engine is loaded from disk (if not already in memory)
          2. Executes the player's decision
          3. Writes world_state back to disk
          4. Appends turn record to turns.jsonl

        Args:
            decision: Free-text player decision (e.g. "联吴抗曹")

        Returns:
            TurnResult with narrative, state_changes, suggestions, etc.
        """
        self._ensure_loaded()

        result = self._engine.execute(decision)

        self._save()
        self._append_turn(decision, result)

        return result

    def plan(self) -> PlanData:
        """Get advisor court dialogue and strategic suggestions.

        Reads current world state from engine, calls the Plan phase.
        Does NOT modify game state or write to disk.
        """
        self._ensure_loaded()
        return self._engine.get_plan()

    def intro(self) -> GameIntro:
        """Get the game intro scene.

        Returns cached intro if available, otherwise generates fresh.
        Does NOT modify game state.
        """
        self._ensure_loaded()
        return self._engine.get_intro()

    def status(self) -> FactionStatus:
        """Get current faction resources (strength, food, treasury, etc.)."""
        self._ensure_loaded()
        return self._engine.get_status()

    def get_turn_history(self) -> list[dict]:
        """Read the full turn history from turns.jsonl.

        Returns:
            List of turn records, oldest first.
        """
        path = self.room_dir / "turns.jsonl"
        if not path.exists():
            return []
        turns = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    turns.append(json.loads(line))
        return turns

    # ── Helpers ────────────────────────────────────────────────

    @property
    def game_id(self) -> str:
        self._ensure_loaded()
        return self._engine.game_id  # type: ignore[no-any-return]

    def _ensure_loaded(self) -> None:
        if self._engine is None:
            # Rebuild from disk
            state_path = self.room_dir / "world_state.json"
            if not state_path.exists():
                raise RuntimeError(f"Room '{self.name}' has no saved state")
            with open(state_path) as f:
                world_state = json.load(f)
            self._engine = DirectEngine.from_dict(world_state)

    def _save(self) -> None:
        """Write world_state.json to disk."""
        if self._engine is None:
            return
        with open(self.room_dir / "world_state.json", "w") as f:
            json.dump(self._engine.to_dict(), f, ensure_ascii=False, indent=2)

    def _append_turn(self, decision: str, result: TurnResult) -> None:
        """Append a turn record to turns.jsonl."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "decision": decision,
            "year": result.get("year"),
            "season": result.get("season"),
            "turn": result.get("turn"),
            "narrative": result.get("narrative", "")[:500],
            "aftermath": result.get("aftermath", ""),
            "state_changes": result.get("state_changes", {}),
        }
        with open(self.room_dir / "turns.jsonl", "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _write_metadata(self) -> None:
        with open(self.room_dir / "metadata.json", "w") as f:
            json.dump(
                {
                    "name": self.name,
                    "faction": self.faction,
                    "created_at": self.created_at,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
