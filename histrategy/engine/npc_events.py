"""NPC Drastic Event Engine — triggers betrayals, defections, and drama.

Executes when an NPC advisor stays at a critical danger mood (PLOTTING)
for multiple consecutive turns.
"""

from __future__ import annotations

import random

from ..state.world_state import WorldState


def process_npc_drastic_events(state: WorldState) -> dict:
    """Scan advisors in PLOTTING state and trigger drastic actions (betrayal/defection).

    Returns a dict with:
      - events_occurred: list of event strings to display
      - state_changes: dict of state changes applied to player faction
      - npc_reactions: list of reactions/notifications
    """
    events_occurred = []
    npc_reactions = []
    player_changes = {
        "strength": 0,
        "treasury": 0,
        "morale": 0,
    }

    player_fac = state.get_player_faction()
    if not player_fac:
        return {
            "events_occurred": events_occurred,
            "state_changes": player_changes,
            "npc_reactions": npc_reactions,
        }

    # Find active NPC factions we could defect to
    other_factions = [fid for fid, fs in state.factions.items() if fs.is_active and fid != state.player_faction_id]
    target_faction_id = random.choice(other_factions) if other_factions else None

    # Scan NPC states
    for cid, npc in list(state.npc_states.items()):
        # Check if PLOTTING for at least 2 consecutive turns (i.e. turns_at_current_mood >= 2)
        if npc.mood.value == "plotting" and npc.turns_at_current_mood >= 2:
            # Trigger betrayal!
            char_name = state.characters.get(cid).name if cid in state.characters else cid
            # If target faction exists, defect to them. Otherwise, become independent.
            if target_faction_id:
                target_fac = state.factions[target_faction_id]
                target_name = target_fac.name

                # Update character allegiance in world state
                if cid in state.characters:
                    state.characters[cid].faction_id = target_faction_id
                    state.characters[cid].loyalty = 80
                    state.characters[cid].role = "general"

                # Apply mechanical impact
                lost_troops = min(5000, int(player_fac.strength * 0.15))
                lost_gold = min(1000, int(player_fac.treasury * 0.20))

                player_fac.strength = max(1000, player_fac.strength - lost_troops)
                player_fac.treasury = max(0, player_fac.treasury - lost_gold)
                player_fac.morale = max(10, player_fac.morale - 10)

                target_fac.strength += lost_troops
                target_fac.treasury += lost_gold

                player_changes["strength"] -= lost_troops
                player_changes["treasury"] -= lost_gold
                player_changes["morale"] -= 10

                evt_msg = f"【叛逃变故】谋臣 {char_name} 怨恨积重难返，率兵卒 {lost_troops} 人，携资金 {lost_gold} 卷，出奔投效了 {target_name}！"
                events_occurred.append(evt_msg)
                npc_reactions.append(f"{char_name} 携军资投奔 {target_name}，引起三军震动。")
            else:
                # Defect and become independent / leave
                if cid in state.characters:
                    state.characters[cid].alive = False  # marks them as gone

                lost_troops = min(2000, int(player_fac.strength * 0.08))
                player_fac.strength = max(1000, player_fac.strength - lost_troops)
                player_fac.morale = max(10, player_fac.morale - 5)

                player_changes["strength"] -= lost_troops
                player_changes["morale"] -= 5

                evt_msg = f"【挂印而去】谋臣 {char_name} 留书一封，挂印弃官而去，不知所踪。部分士卒 {lost_troops} 人随其解甲归田。"
                events_occurred.append(evt_msg)
                npc_reactions.append(f"{char_name} 弃官而去，主公帐下痛失一员英才。")

            # Remove from NPC states list (they are no longer player's advisor/NPC state to track)
            state.npc_states.pop(cid, None)

    return {
        "events_occurred": events_occurred,
        "state_changes": player_changes,
        "npc_reactions": npc_reactions,
    }
