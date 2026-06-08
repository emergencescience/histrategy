def calculate_grain_yield(base_area: float, tech_multiplier: float, season: str) -> float:
    """
    Calculate grain yield based on base area, technology multiplier, and season.
    season: 'spring', 'summer', 'autumn', 'winter'
    """
    season_multipliers = {
        "spring": 0.5,
        "summer": 1.0,
        "autumn": 1.5,
        "winter": 1.0
    }
    season_factor = season_multipliers.get(season.lower(), 1.0)
    return base_area * tech_multiplier * season_factor
