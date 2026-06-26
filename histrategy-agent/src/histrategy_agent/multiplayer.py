"""
MultiplayerState — group chat multiplayer support (v2: faction-only, server-backed).

histrategy server handles all state persistence (SQL DB).
histrategy-agent is a thin client — no local file persistence, no user_id tracking.
Agents identify by faction_id, not user_id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class GamePhase(Enum):
    LOBBY = "lobby"
    PLAYING = "playing"
    FINISHED = "finished"


@dataclass
class FactionPlayer:
    """A faction controlled by a player in a multiplayer room.

    No user_id — identity is faction-based. histrategy server
    handles auth and faction assignment.
    """

    faction_id: str
    display_name: str = ""
    is_spectator: bool = False
    joined_at: str = ""

    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.faction_id
        if not self.joined_at:
            self.joined_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "faction_id": self.faction_id,
            "display_name": self.display_name,
            "is_spectator": self.is_spectator,
            "joined_at": self.joined_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FactionPlayer:
        return cls(
            faction_id=data["faction_id"],
            display_name=data.get("display_name", ""),
            is_spectator=data.get("is_spectator", False),
            joined_at=data.get("joined_at", ""),
        )


@dataclass
class MultiplayerSession:
    """Thin client-side wrapper around histrategy server room state.

    No local file persistence — all state lives on the histrategy server (SQL DB).
    No user_id tracking — agents identify by faction_id.
    """

    session_id: str
    room_id: str = ""  # histrategy server room ID
    factions: dict[str, FactionPlayer] = field(default_factory=dict)  # faction_id → player
    game_phase: GamePhase = GamePhase.LOBBY
    max_players: int = 7

    # ─── Serialization ──────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "room_id": self.room_id,
            "factions": {fid: fp.to_dict() for fid, fp in self.factions.items()},
            "game_phase": self.game_phase.value,
            "max_players": self.max_players,
        }

    @classmethod
    def from_dict(cls, data: dict) -> MultiplayerSession:
        session = cls(
            session_id=data["session_id"],
            room_id=data.get("room_id", ""),
            max_players=data.get("max_players", 7),
        )
        session.factions = {
            fid: FactionPlayer.from_dict(fp_data)
            for fid, fp_data in data.get("factions", {}).items()
        }
        session.game_phase = GamePhase(data.get("game_phase", "lobby"))
        return session

    # ─── Display ────────────────────────────────────────

    def get_status_message(self) -> str:
        """Render multiplayer status for the group chat."""
        phase_cn = {
            GamePhase.LOBBY: "等待中",
            GamePhase.PLAYING: "进行中",
            GamePhase.FINISHED: "已结束",
        }

        lines = []
        lines.append(f"👥 **多人游戏** — {phase_cn.get(self.game_phase, '未知')}")
        if self.room_id:
            lines.append(f"| 房间 | `{self.room_id[:12]}...` |")
        lines.append(f"| 人数 | {len(self.factions)}/{self.max_players} |")
        lines.append("")

        if self.factions:
            lines.append("**势力列表**")
            for fid, fp in self.factions.items():
                spec_mark = " 👁️" if fp.is_spectator else ""
                faction_name = {
                    "shu": "蜀(刘备)",
                    "cao": "魏(曹操)",
                    "wu": "吴(孙权)",
                    "liubiao": "荆(刘表)",
                    "liuzhang": "益(刘璋)",
                }.get(fid, fid)
                lines.append(f"- {fp.display_name}{spec_mark} | {faction_name}")
            lines.append("")

        if self.game_phase == GamePhase.LOBBY:
            lines.append("📋 /histrategy start — 开始游戏")

        return "\n".join(lines).strip()
