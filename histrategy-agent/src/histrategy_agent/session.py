"""
Game session manager — persistent sessions keyed by (platform, chat_id).

Sessions persist to ~/.histrategy/sessions/{platform}/{chat_id}/ as JSON.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from histrategy_engine import (
    Army,
    Character,
    FactionState,
    HistoricalMode,
    Season,
    TerrainType,
    Territory,
    UnitType,
    WorldState,
)

# ─── JSON serialization helpers ──────────────────────────────


def _to_dict(obj: Any) -> Any:
    """Convert dataclasses and enums to plain dicts/lists/primitives."""
    if isinstance(obj, Enum):
        return obj.value
    if is_dataclass(obj) and not isinstance(obj, type):
        result = {}
        for f in obj.__dataclass_fields__:
            value = getattr(obj, f)
            result[f] = _to_dict(value)
        return result
    if isinstance(obj, dict):
        return {_to_dict(k): _to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_dict(item) for item in obj]
    return obj


def _from_dict(cls: type, data: dict) -> Any:
    """Reconstruct a dataclass from a plain dict, restoring enums."""
    if not isinstance(data, dict):
        return data
    # Use get_type_hints to resolve string annotations (from __future__ import annotations)
    try:
        from typing import get_type_hints

        field_types = get_type_hints(cls)
    except Exception:
        field_types = {}
        for f_name, f_def in cls.__dataclass_fields__.items():
            field_types[f_name] = f_def.type
    kwargs = {}
    for key, value in data.items():
        if key not in field_types:
            kwargs[key] = value
            continue
        ft = field_types[key]
        kwargs[key] = _coerce_value(ft, value)
    return cls(**kwargs)


def _coerce_value(ft: type, value: Any) -> Any:
    """Restore typed value — enums, nested dataclasses."""
    origin = getattr(ft, "__origin__", None)
    if isinstance(ft, type) and issubclass(ft, Enum):
        return ft(value)
    if isinstance(ft, type) and is_dataclass(ft):
        return _from_dict(ft, value) if isinstance(value, dict) else value
    if origin is dict:
        if isinstance(value, dict):
            args = getattr(ft, "__args__", ())
            kt = args[0] if args else str
            vt = args[1] if len(args) > 1 else Any
            return {_coerce_value(kt, k): _coerce_value(vt, v) for k, v in value.items()}
        return value
    if origin is list:
        if isinstance(value, list):
            args = getattr(ft, "__args__", ())
            it = args[0] if args else Any
            return [_coerce_value(it, item) for item in value]
        return value
    return value


# ─── Data model ─────────────────────────────────────────────


@dataclass
class GameSession:
    """An active game session in an IM chat."""

    session_id: str  # "{platform}:{chat_id}"
    platform: str  # "feishu", "telegram", etc.
    chat_id: str  # IM chat/group ID
    world_state: WorldState  # Current world state snapshot
    turn_number: int
    player_faction_id: str
    created_at: str  # ISO timestamp
    updated_at: str  # ISO timestamp
    is_multiplayer: bool = False
    player_ids: list[str] = field(default_factory=list)


# ─── GameSessionManager ─────────────────────────────────────


class GameSessionManager:
    """Manages all active game sessions, keyed by (platform, chat_id)."""

    def __init__(self, data_dir: str | None = None):
        if data_dir is None:
            default = os.environ.get("HISTRATEGY_DATA_DIR", os.path.expanduser("~/.histrategy"))
            data_dir = os.path.join(default, "sessions")
        self.data_dir = Path(data_dir)

    def _session_dir(self, platform: str, chat_id: str) -> Path:
        return self.data_dir / platform / chat_id

    def _save_path(self, platform: str, chat_id: str) -> Path:
        return self._session_dir(platform, chat_id) / "world_state.json"

    def _meta_path(self, platform: str, chat_id: str) -> Path:
        return self._session_dir(platform, chat_id) / "session_meta.json"

    def get_session(self, platform: str, chat_id: str) -> GameSession | None:
        """Get session if it exists, else None."""
        meta_path = self._meta_path(platform, chat_id)
        ws_path = self._save_path(platform, chat_id)
        if not meta_path.exists() or not ws_path.exists():
            return None

        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        with open(ws_path, encoding="utf-8") as f:
            ws_data = json.load(f)

        world_state = _from_dict(WorldState, ws_data)
        return GameSession(
            session_id=meta["session_id"],
            platform=meta["platform"],
            chat_id=meta["chat_id"],
            world_state=world_state,
            turn_number=meta["turn_number"],
            player_faction_id=meta["player_faction_id"],
            created_at=meta["created_at"],
            updated_at=meta["updated_at"],
            is_multiplayer=meta.get("is_multiplayer", False),
            player_ids=meta.get("player_ids", []),
        )

    def get_or_create(
        self,
        platform: str,
        chat_id: str,
        faction_id: str = "shu",
        scenario: str = "207",
    ) -> GameSession:
        """Load existing session or create a new one."""
        existing = self.get_session(platform, chat_id)
        if existing:
            return existing
        return self._create_session(platform, chat_id, faction_id, scenario)

    def _create_session(self, platform: str, chat_id: str, faction_id: str, scenario: str) -> GameSession:
        """Create a new game session with a minimal WorldState for scenario 207."""
        now = datetime.now(timezone.utc).isoformat()

        # Build minimal WorldState for 207 scenario
        world_state = self._build_initial_world(faction_id, scenario)

        session = GameSession(
            session_id=f"{platform}:{chat_id}",
            platform=platform,
            chat_id=chat_id,
            world_state=world_state,
            turn_number=1,
            player_faction_id=faction_id,
            created_at=now,
            updated_at=now,
        )
        self.save_session(session)
        return session

    def _build_initial_world(self, faction_id: str, scenario: str) -> WorldState:
        """Build the initial WorldState for a new game session.

        Uses the engine's knowledge loader (build_world_state) when available,
        which reads from histrategy-knowledge/ JSON data. Falls back to the
        hardcoded defaults only when the engine package is not installed.
        """
        # Try the engine's canonical loader first
        try:
            from histrategy.engine.loader import build_world_state

            return build_world_state(faction_id, scenario)
        except ImportError:
            pass

        # Fallback: hardcoded minimal world for standalone agent use
        return self._build_initial_world_fallback(faction_id, scenario)

    def _build_initial_world_fallback(self, faction_id: str, scenario: str) -> WorldState:
        """Hardcoded fallback world state (used when histrategy-engine is not installed).

        This data is a subset of what histrategy-knowledge/ provides.
        When the main histrategy package is available, prefer build_world_state().
        """
        territories = {
            "xinye": Territory(
                id="xinye",
                name="新野",
                owner_id="shu",
                population=30000,
                development=25,
                terrain_type=TerrainType.PLAINS,
                climate_zone="central",
                fertility=6,
                neighbors=["wancheng", "xiangyang"],
            ),
            "wancheng": Territory(
                id="wancheng",
                name="宛城",
                owner_id="cao",
                population=50000,
                development=45,
                terrain_type=TerrainType.PLAINS,
                climate_zone="central",
                fertility=7,
                neighbors=["xinye", "xuchang", "luoyang"],
            ),
            "xuchang": Territory(
                id="xuchang",
                name="许昌",
                owner_id="cao",
                population=100000,
                development=70,
                terrain_type=TerrainType.PLAINS,
                climate_zone="central",
                fertility=7,
                neighbors=["wancheng", "luoyang", "ye", "xiapi"],
            ),
            "luoyang": Territory(
                id="luoyang",
                name="洛阳",
                owner_id="cao",
                population=80000,
                development=65,
                terrain_type=TerrainType.PLAINS,
                climate_zone="north",
                fertility=7,
                neighbors=["wancheng", "xuchang", "ye"],
            ),
            "ye": Territory(
                id="ye",
                name="邺城",
                owner_id="cao",
                population=120000,
                development=75,
                terrain_type=TerrainType.PLAINS,
                climate_zone="north",
                fertility=8,
                neighbors=["xuchang", "luoyang", "ji"],
            ),
            "ji": Territory(
                id="ji",
                name="蓟县",
                owner_id="cao",
                population=60000,
                development=40,
                terrain_type=TerrainType.PLAINS,
                climate_zone="north",
                fertility=5,
                horse_resource=True,
                neighbors=["ye"],
            ),
            "xiangyang": Territory(
                id="xiangyang",
                name="襄阳",
                owner_id="liubiao",
                population=80000,
                development=55,
                terrain_type=TerrainType.PLAINS,
                climate_zone="central",
                fertility=8,
                has_river=True,
                neighbors=["xinye", "jiangling", "chaisang"],
            ),
            "jiangling": Territory(
                id="jiangling",
                name="江陵",
                owner_id="liubiao",
                population=60000,
                development=50,
                terrain_type=TerrainType.PLAINS,
                climate_zone="central",
                fertility=8,
                has_river=True,
                neighbors=["xiangyang", "chaisang", "chengdu"],
            ),
            "chengdu": Territory(
                id="chengdu",
                name="成都",
                owner_id="liuzhang",
                population=100000,
                development=60,
                terrain_type=TerrainType.MOUNTAIN,
                climate_zone="south",
                fertility=8,
                has_river=True,
                neighbors=["jiangling", "hanshui"],
            ),
            "hanshui": Territory(
                id="hanshui",
                name="汉中",
                owner_id="liuzhang",
                population=40000,
                development=35,
                terrain_type=TerrainType.MOUNTAIN,
                climate_zone="central",
                fertility=5,
                neighbors=["chengdu"],
            ),
            "jianye": Territory(
                id="jianye",
                name="建业",
                owner_id="wu",
                population=70000,
                development=55,
                terrain_type=TerrainType.PLAINS,
                climate_zone="south",
                fertility=7,
                has_river=True,
                has_coast=True,
                neighbors=["chaisang", "wu"],
            ),
            "chaisang": Territory(
                id="chaisang",
                name="柴桑",
                owner_id="wu",
                population=40000,
                development=40,
                terrain_type=TerrainType.PLAINS,
                climate_zone="south",
                fertility=7,
                has_river=True,
                neighbors=["xiangyang", "jiangling", "jianye", "wu"],
            ),
            "wu": Territory(
                id="wu",
                name="吴郡",
                owner_id="wu",
                population=50000,
                development=45,
                terrain_type=TerrainType.PLAINS,
                climate_zone="south",
                fertility=7,
                has_river=True,
                has_coast=True,
                neighbors=["jianye", "chaisang"],
            ),
            "xiapi": Territory(
                id="xiapi",
                name="下邳",
                owner_id="cao",
                population=50000,
                development=45,
                terrain_type=TerrainType.PLAINS,
                climate_zone="central",
                fertility=7,
                has_coast=True,
                neighbors=["xuchang"],
            ),
        }

        factions = {
            "shu": FactionState(
                id="shu",
                name="刘备",
                ruler_id="liubei",
                capital="xinye",
                territories=["xinye"],
                prestige=35,
                strength_actual=5000,
                strength_estimated=5000,
                treasury=3000,
                food=2000,
                tax_rate=0.2,
                morale_actual=70,
                morale_estimated=70,
                economy_actual=50,
                economy_estimated=50,
                relations={"cao": -80, "wu": 20, "liubiao": 40, "liuzhang": 10},
                aggression=0.3,
                cunning=0.3,
                caution=0.7,
                diplomacy=0.8,
                development_focus=0.8,
                mercy=0.95,
            ),
            "cao": FactionState(
                id="cao",
                name="曹操",
                ruler_id="caocao",
                capital="xuchang",
                territories=["xuchang", "wancheng", "luoyang", "ye", "ji", "xiapi"],
                prestige=90,
                strength_actual=150000,
                strength_estimated=150000,
                treasury=50000,
                food=30000,
                tax_rate=0.4,
                morale_actual=80,
                morale_estimated=80,
                economy_actual=60,
                economy_estimated=60,
                relations={"shu": -80, "wu": -30, "liubiao": -20, "liuzhang": -10},
                aggression=0.8,
                cunning=0.9,
                caution=0.3,
                diplomacy=0.5,
                development_focus=0.6,
                mercy=0.2,
            ),
            "wu": FactionState(
                id="wu",
                name="孙权",
                ruler_id="sunquan",
                capital="jianye",
                territories=["jianye", "chaisang", "wu"],
                prestige=60,
                strength_actual=60000,
                strength_estimated=60000,
                treasury=15000,
                food=10000,
                tax_rate=0.3,
                morale_actual=75,
                morale_estimated=75,
                economy_actual=55,
                economy_estimated=55,
                relations={"shu": 20, "cao": -30},
                aggression=0.6,
                cunning=0.6,
                caution=0.5,
                diplomacy=0.6,
                development_focus=0.6,
                mercy=0.5,
            ),
            "liubiao": FactionState(
                id="liubiao",
                name="刘表",
                ruler_id="liubiao",
                capital="xiangyang",
                territories=["xiangyang", "jiangling"],
                prestige=50,
                strength_actual=40000,
                strength_estimated=40000,
                treasury=10000,
                food=8000,
                tax_rate=0.3,
                morale_actual=50,
                morale_estimated=50,
                economy_actual=50,
                economy_estimated=50,
                relations={"shu": 40, "cao": -20, "wu": -10},
            ),
            "liuzhang": FactionState(
                id="liuzhang",
                name="刘璋",
                ruler_id="liuzhang",
                capital="chengdu",
                territories=["chengdu", "hanshui"],
                prestige=30,
                strength_actual=50000,
                strength_estimated=50000,
                treasury=12000,
                food=15000,
                tax_rate=0.3,
                morale_actual=55,
                morale_estimated=55,
                economy_actual=40,
                economy_estimated=40,
                relations={"shu": 10, "cao": -10, "liubiao": 20},
            ),
        }

        characters = {
            "liubei": Character(
                id="liubei",
                name="刘备",
                alias="玄德",
                faction_id="shu",
                location="xinye",
                leadership=80,
                might=70,
                intelligence=72,
                politics=82,
                charisma=99,
                skills=["仁德", "号召", "仁政"],
                birth=161,
                death=223,
            ),
            "guanyu": Character(
                id="guanyu",
                name="关羽",
                alias="云长",
                faction_id="shu",
                location="xinye",
                leadership=95,
                might=98,
                intelligence=75,
                politics=62,
                charisma=88,
                skills=["骑兵指挥", "青龙偃月", "水淹"],
                sworn_brothers=["liubei", "zhangfei"],
                birth=160,
                death=220,
            ),
            "zhangfei": Character(
                id="zhangfei",
                name="张飞",
                alias="翼德",
                faction_id="shu",
                location="xinye",
                leadership=85,
                might=98,
                intelligence=45,
                politics=30,
                charisma=50,
                skills=["骑兵指挥", "丈八蛇矛", "据水断桥"],
                sworn_brothers=["liubei", "guanyu"],
                birth=165,
                death=221,
            ),
            "zhugeliang": Character(
                id="zhugeliang",
                name="诸葛亮",
                alias="孔明",
                faction_id="shu",
                location="longzhong",
                leadership=92,
                might=32,
                intelligence=100,
                politics=98,
                charisma=90,
                skills=["火攻", "奇门遁甲", "屯田", "八阵图", "连弩"],
                birth=181,
                death=234,
            ),
            "zhaoyun": Character(
                id="zhaoyun",
                name="赵云",
                alias="子龙",
                faction_id="shu",
                location="xinye",
                leadership=89,
                might=95,
                intelligence=76,
                politics=67,
                charisma=82,
                skills=["枪术", "单骑救主", "骑兵指挥"],
                birth=168,
                death=229,
            ),
            "caocao": Character(
                id="caocao",
                name="曹操",
                alias="孟德",
                faction_id="cao",
                location="xuchang",
                leadership=98,
                might=72,
                intelligence=93,
                politics=94,
                charisma=92,
                skills=["统率", "谋略", "诗文", "屯田"],
                birth=155,
                death=220,
            ),
            "sunquan": Character(
                id="sunquan",
                name="孙权",
                alias="仲谋",
                faction_id="wu",
                location="jianye",
                leadership=75,
                might=60,
                intelligence=82,
                politics=88,
                charisma=85,
                skills=["水战", "外交", "权谋"],
                birth=182,
                death=252,
            ),
            "zhouyu": Character(
                id="zhouyu",
                name="周瑜",
                alias="公瑾",
                faction_id="wu",
                location="chaisang",
                leadership=95,
                might=65,
                intelligence=94,
                politics=80,
                charisma=85,
                skills=["水战", "火攻", "音律"],
                birth=175,
                death=210,
            ),
        }

        armies = {}
        if faction_id in factions:
            army_id = f"army_{faction_id}_1"
            capital = factions[faction_id].capital
            armies[army_id] = Army(
                id=army_id,
                faction_id=faction_id,
                location=capital,
                commander_id="",
                units={UnitType.INFANTRY: 3000, UnitType.CAVALRY: 500, UnitType.ARCHER: 1500},
                morale=80,
                training=1.0,
                supply=30,
            )

        return WorldState(
            year=207,
            season=Season.WINTER,
            turn_number=1,
            scenario=scenario,
            player_faction_id=faction_id,
            territories=territories,
            characters=characters,
            factions=factions,
            armies=armies,
            historical_mode=HistoricalMode.DIVERGENT,
            player_deviation=0.0,
        )

    def save_session(self, session: GameSession) -> None:
        """Persist world_state to disk as JSON."""
        session_dir = self._session_dir(session.platform, session.chat_id)
        session_dir.mkdir(parents=True, exist_ok=True)

        session.updated_at = datetime.now(timezone.utc).isoformat()

        # Save world state
        ws_data = _to_dict(session.world_state)
        with open(self._save_path(session.platform, session.chat_id), "w", encoding="utf-8") as f:
            json.dump(ws_data, f, ensure_ascii=False, indent=2)

        # Save meta
        meta = {
            "session_id": session.session_id,
            "platform": session.platform,
            "chat_id": session.chat_id,
            "turn_number": session.turn_number,
            "player_faction_id": session.player_faction_id,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "is_multiplayer": session.is_multiplayer,
            "player_ids": session.player_ids,
        }
        with open(self._meta_path(session.platform, session.chat_id), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def delete_session(self, platform: str, chat_id: str) -> bool:
        """Delete a session's save files."""
        session_dir = self._session_dir(platform, chat_id)
        if not session_dir.exists():
            return False
        shutil.rmtree(session_dir)
        return True

    def list_sessions(self, platform: str | None = None) -> list[GameSession]:
        """List all sessions, optionally filtered by platform."""
        sessions: list[GameSession] = []
        if not self.data_dir.exists():
            return sessions

        platforms = [platform] if platform else os.listdir(self.data_dir)
        for p in platforms:
            p_dir = self.data_dir / p
            if not p_dir.is_dir():
                continue
            for chat_id in os.listdir(p_dir):
                session = self.get_session(p, chat_id)
                if session:
                    sessions.append(session)
        return sessions
