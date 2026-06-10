def calculate_loyalty_change(legitimacy: int, politics: int) -> int:
    """
    Calculate annual loyalty change based on faction legitimacy and character politics.
    delta_loyalty = (legitimacy - 50) / 10 + (politics > 80 ? -2 : 0)
    """
    delta = (legitimacy - 50) / 10.0
    if politics > 80:
        delta -= 2.0

    return int(delta)
