from dataclasses import dataclass


@dataclass
class LegitimacyState:
    current_score: int = 50


def update_legitimacy(state: LegitimacyState, events_list: list[str]) -> LegitimacyState:
    """
    Update legitimacy score based on events.
    """
    for event in events_list:
        if event == "win_battle":
            state.current_score += 5
        elif event == "heavy_tax":
            state.current_score -= 10

    # Clamp to 0-100
    state.current_score = max(0, min(100, state.current_score))
    return state
