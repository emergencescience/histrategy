"""
MultiplayerState — group chat multiplayer support.

Enables multiple players in a group chat to join and take turns
controlling different factions in the same game world.
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class GamePhase(Enum):
    LOBBY = "lobby"
    PLAYING = "playing"
    FINISHED = "finished"


@dataclass
class PlayerSlot:
    """A player's slot in a multiplayer session."""

    user_id: str
    faction_id: str
    display_name: str = ""
    is_spectator: bool = False
    joined_at: str = ""

    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.user_id
        if not self.joined_at:
            self.joined_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "faction_id": self.faction_id,
            "display_name": self.display_name,
            "is_spectator": self.is_spectator,
            "joined_at": self.joined_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PlayerSlot:
        return cls(
            user_id=data["user_id"],
            faction_id=data["faction_id"],
            display_name=data.get("display_name", ""),
            is_spectator=data.get("is_spectator", False),
            joined_at=data.get("joined_at", ""),
        )


@dataclass
class MultiplayerSession:
    """Manages multiplayer state for a group chat session."""

    session_id: str
    host_user_id: str
    players: dict[str, PlayerSlot] = field(default_factory=dict)  # user_id → PlayerSlot
    turn_order: list[str] = field(default_factory=list)  # user_ids in play order
    current_turn_index: int = 0
    game_phase: GamePhase = GamePhase.LOBBY
    max_players: int = 7

    def add_player(self, user_id: str, display_name: str = "") -> PlayerSlot:
        """Add a player. Auto-assigns an available faction. Returns the slot."""
        if user_id in self.players:
            return self.players[user_id]

        if self.game_phase != GamePhase.LOBBY:
            raise ValueError("游戏已经开始，无法加入")

        if len(self.players) >= self.max_players:
            raise ValueError(f"已满员（最多{self.max_players}人）")

        # Auto-assign faction
        assigned_factions = {slot.faction_id for slot in self.players.values()}
        available_factions = [
            fid for fid in ["shu", "cao", "wu", "liubiao", "liuzhang", "yuan", "ma"] if fid not in assigned_factions
        ]
        faction_id = available_factions[0] if available_factions else f"custom_{user_id}"

        slot = PlayerSlot(
            user_id=user_id,
            faction_id=faction_id,
            display_name=display_name or user_id,
        )
        self.players[user_id] = slot
        self._save_to_file()
        return slot

    def remove_player(self, user_id: str) -> bool:
        """Remove a player. Cannot remove the host."""
        if user_id == self.host_user_id:
            return False
        if user_id in self.players:
            del self.players[user_id]
            if user_id in self.turn_order:
                self.turn_order.remove(user_id)
            self._save_to_file()
            return True
        return False

    def start_game(self) -> None:
        """Transition from LOBBY to PLAYING. Shuffle turn order."""
        if self.game_phase != GamePhase.LOBBY:
            return
        if len(self.players) < 1:
            return

        self.turn_order = list(self.players.keys())
        random.shuffle(self.turn_order)
        self.current_turn_index = 0
        self.game_phase = GamePhase.PLAYING
        self._save_to_file()

    def get_current_player(self) -> PlayerSlot | None:
        """Who should act this turn?"""
        if self.game_phase != GamePhase.PLAYING:
            return None
        if not self.turn_order:
            return None
        if self.current_turn_index >= len(self.turn_order):
            return None
        user_id = self.turn_order[self.current_turn_index]
        return self.players.get(user_id)

    def advance_turn(self) -> PlayerSlot | None:
        """Move to next player. Returns new current player or None if round complete."""
        if self.game_phase != GamePhase.PLAYING:
            return None

        self.current_turn_index += 1

        # Check if round is complete
        if self.current_turn_index >= len(self.turn_order):
            # Start new round
            self.current_turn_index = 0

        return self.get_current_player()

    def end_game(self) -> None:
        """End the game."""
        self.game_phase = GamePhase.FINISHED
        self._save_to_file()

    # ─── Persistence ──────────────────────────────────────

    def _file_path(self) -> Path:
        """Filesystem path for this session's save file."""
        data_dir = os.environ.get("HISTRATEGY_DATA_DIR", os.path.expanduser("~/.histrategy"))
        sessions_dir = Path(data_dir) / "sessions" / "multiplayer"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        return sessions_dir / f"{self.session_id}.json"

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "host_user_id": self.host_user_id,
            "players": {uid: slot.to_dict() for uid, slot in self.players.items()},
            "turn_order": list(self.turn_order),
            "current_turn_index": self.current_turn_index,
            "game_phase": self.game_phase.value,
            "max_players": self.max_players,
        }

    def save(self, file_path: str | Path | None = None) -> None:
        """Persist this session to disk (JSON)."""
        path = Path(file_path) if file_path else self._file_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    def _save_to_file(self) -> None:
        """Auto-save after state mutation. Suppresses errors so game continues if disk is full."""
        try:
            self.save()
        except OSError:
            pass

    @classmethod
    def load(cls, session_id: str) -> MultiplayerSession | None:
        """Load a session from disk. Returns None if not found."""
        data_dir = os.environ.get("HISTRATEGY_DATA_DIR", os.path.expanduser("~/.histrategy"))
        path = Path(data_dir) / "sessions" / "multiplayer" / f"{session_id}.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> MultiplayerSession:
        session = cls(
            session_id=data["session_id"],
            host_user_id=data["host_user_id"],
            max_players=data.get("max_players", 7),
        )
        session.players = {uid: PlayerSlot.from_dict(slot_data) for uid, slot_data in data.get("players", {}).items()}
        session.turn_order = list(data.get("turn_order", []))
        session.current_turn_index = data.get("current_turn_index", 0)
        session.game_phase = GamePhase(data.get("game_phase", "lobby"))
        return session

    def get_status_message(self) -> str:
        """Render multiplayer status for the group chat."""
        phase_cn = {
            GamePhase.LOBBY: "等待中",
            GamePhase.PLAYING: "进行中",
            GamePhase.FINISHED: "已结束",
        }

        lines = []
        lines.append(f"👥 **多人游戏** — {phase_cn.get(self.game_phase, '未知')}")
        lines.append(f"| 人数 | {len(self.players)}/{self.max_players} |")
        lines.append("")

        if self.players:
            lines.append("**玩家列表**")
            for user_id, slot in self.players.items():
                host_mark = " 👑" if user_id == self.host_user_id else ""
                turn_mark = (
                    " 🎯"
                    if (
                        self.game_phase == GamePhase.PLAYING and user_id == self.turn_order[self.current_turn_index]
                        if self.turn_order and self.current_turn_index < len(self.turn_order)
                        else False
                    )
                    else ""
                )
                spec_mark = " 👁️" if slot.is_spectator else ""
                faction_name = {
                    "shu": "蜀(刘备)",
                    "cao": "魏(曹操)",
                    "wu": "吴(孙权)",
                    "liubiao": "荆(刘表)",
                    "liuzhang": "益(刘璋)",
                }.get(slot.faction_id, slot.faction_id)
                lines.append(f"- {slot.display_name}{host_mark}{turn_mark}{spec_mark} | {faction_name}")
            lines.append("")

        if self.game_phase == GamePhase.PLAYING:
            current = self.get_current_player()
            if current:
                lines.append(f"🎯 当前行动: **{current.display_name}** ({current.faction_id})")
            lines.append("")

        if self.game_phase == GamePhase.LOBBY:
            lines.append("📋 /histrategy join — 加入游戏")
            lines.append("📋 /histrategy start — 开始游戏")

        return "\n".join(lines).strip()
