from histrategy_engine.domestic.grain import calculate_grain_yield


def test_grain_yield_seasonality():
    base = 1000.0
    tech = 1.2

    spring_yield = calculate_grain_yield(base, tech, "spring")
    summer_yield = calculate_grain_yield(base, tech, "summer")
    autumn_yield = calculate_grain_yield(base, tech, "autumn")
    calculate_grain_yield(base, tech, "winter")

    assert autumn_yield > spring_yield
    assert autumn_yield > summer_yield
    assert spring_yield < summer_yield
    assert autumn_yield == 1000.0 * 1.2 * 1.5
