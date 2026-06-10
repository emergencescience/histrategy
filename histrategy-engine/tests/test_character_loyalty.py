from histrategy_engine.character.loyalty import calculate_loyalty_change


def test_loyalty_change_normal():
    # Legitimacy 50, politics 50 -> delta = 0
    assert calculate_loyalty_change(50, 50) == 0


def test_loyalty_change_high_legitimacy():
    # Legitimacy 80, politics 50 -> delta = 3
    assert calculate_loyalty_change(80, 50) == 3


def test_loyalty_change_high_politics_rebel():
    # Legitimacy 30, politics 90 -> delta = -2 - 2 = -4
    # (30-50)/10 = -2, -2 - 2 = -4
    assert calculate_loyalty_change(30, 90) == -4

    # Legitimacy 80, politics 90 -> delta = 3 - 2 = 1
    assert calculate_loyalty_change(80, 90) == 1
