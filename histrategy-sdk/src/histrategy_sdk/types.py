"""Type definitions for histrategy-sdk."""

from __future__ import annotations

from typing import TypedDict


class FactionStatus(TypedDict, total=False):
    """Current status of the player's faction."""
    name: str
    faction_id: str
    strength: int
    food: int
    treasury: int
    territories: list[str]
    territory_names: list[str]
    morale: int
    is_active: bool
    year: int
    season: str
    turn: int


class GameIntro(TypedDict):
    """Response from create_game / restore_game."""
    game_id: str
    scenario: str
    faction: str
    narrative: str
    suggestions: list[str]
    faction_status: FactionStatus


class PlanData(TypedDict):
    """Response from get_plan."""
    game_id: str
    court_dialogue: str
    suggestions: list[str]
    season_summary: str
    year: int
    season: str
    turn: int
    faction_status: FactionStatus


class TurnResult(TypedDict):
    """Response from execute_command."""
    game_id: str
    narrative: str
    aftermath: str
    state_changes: dict[str, int]
    events_occurred: list[str]
    npc_actions: list[str]
    new_suggestions: list[str]
    game_over: dict | None
    faction_status: FactionStatus
    year: int
    season: str
    turn: int
    token_usage: TokenUsage


class TokenUsage(TypedDict, total=False):
    """LLM token consumption for a turn."""
    command_tokens: int
    plan_tokens: int
    npc_tokens: int
    sim_tokens: int


class RestoreResult(TypedDict):
    """Response from restore_game."""
    game_id: str
    scenario: str
    faction: str
    faction_status: FactionStatus
    restored: bool
    restored_turn: int
    restored_year: int
