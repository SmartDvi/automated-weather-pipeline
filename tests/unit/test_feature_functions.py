from datetime import UTC, datetime

from weatherml.features.functions import (
    aqi_composite_risk,
    cyclical_encode,
    dew_point_c,
    heat_index_c,
    pressure_trend,
    rate_of_change,
    storm_indicator,
    wind_chill_c,
)


class TestHeatIndex:
    def test_below_threshold_returns_none(self):
        assert heat_index_c(20.0, 80.0) is None

    def test_at_threshold_is_computed(self):
        assert heat_index_c(26.7, 70.0) is not None

    def test_missing_inputs_return_none(self):
        assert heat_index_c(None, 80.0) is None
        assert heat_index_c(30.0, None) is None

    def test_hot_humid_gives_higher_than_raw_temp(self):
        # classic "feels hotter than it is" case
        result = heat_index_c(32.0, 70.0)
        assert result is not None
        assert result > 32.0


class TestDewPoint:
    def test_typical_value_is_below_temperature(self):
        result = dew_point_c(25.0, 50.0)
        assert result is not None
        assert result < 25.0

    def test_saturated_air_dew_point_equals_temperature(self):
        result = dew_point_c(20.0, 100.0)
        assert abs(result - 20.0) < 0.5

    def test_zero_humidity_returns_none(self):
        assert dew_point_c(20.0, 0.0) is None

    def test_missing_inputs_return_none(self):
        assert dew_point_c(None, 50.0) is None


class TestWindChill:
    def test_valid_cold_windy_conditions(self):
        result = wind_chill_c(0.0, 20.0)
        assert result is not None
        assert result < 0.0

    def test_too_warm_returns_none(self):
        assert wind_chill_c(15.0, 20.0) is None

    def test_too_calm_returns_none(self):
        assert wind_chill_c(0.0, 2.0) is None

    def test_boundary_exactly_10c_is_valid(self):
        assert wind_chill_c(10.0, 20.0) is not None

    def test_boundary_just_above_10c_is_none(self):
        assert wind_chill_c(10.01, 20.0) is None


class TestRateOfChange:
    def test_computes_difference(self):
        assert rate_of_change(20.0, 15.0) == 5.0

    def test_missing_current_returns_none(self):
        assert rate_of_change(None, 15.0) is None

    def test_missing_past_returns_none(self):
        assert rate_of_change(20.0, None) is None


class TestPressureTrend:
    def test_falling_pressure_gives_negative_slope(self):
        times = [datetime(2026, 1, 1, h, tzinfo=UTC) for h in range(4)]
        pressures = [1015.0, 1013.0, 1011.0, 1009.0]
        slope = pressure_trend(times, pressures)
        assert slope is not None
        assert slope < 0

    def test_rising_pressure_gives_positive_slope(self):
        times = [datetime(2026, 1, 1, h, tzinfo=UTC) for h in range(4)]
        pressures = [1000.0, 1002.0, 1004.0, 1006.0]
        slope = pressure_trend(times, pressures)
        assert slope > 0

    def test_single_point_returns_none(self):
        times = [datetime(2026, 1, 1, 0, tzinfo=UTC)]
        assert pressure_trend(times, [1013.0]) is None

    def test_empty_returns_none(self):
        assert pressure_trend([], []) is None

    def test_ignores_none_values(self):
        times = [datetime(2026, 1, 1, h, tzinfo=UTC) for h in range(3)]
        pressures = [1010.0, None, 1012.0]
        assert pressure_trend(times, pressures) is not None


class TestCyclicalEncode:
    def test_returns_four_values_in_unit_range(self):
        result = cyclical_encode(datetime(2026, 6, 15, 12, 30, tzinfo=UTC))
        assert len(result) == 4
        for v in result:
            assert -1.0 <= v <= 1.0

    def test_midnight_and_noon_are_distinguishable(self):
        midnight = cyclical_encode(datetime(2026, 6, 15, 0, 0, tzinfo=UTC))
        noon = cyclical_encode(datetime(2026, 6, 15, 12, 0, tzinfo=UTC))
        assert midnight[:2] != noon[:2]

    def test_hour_zero_and_hour_24_equivalent_continuity(self):
        # 23:59 and 00:00 should be close in cyclical space, not far apart
        late = cyclical_encode(datetime(2026, 6, 15, 23, 59, tzinfo=UTC))
        early = cyclical_encode(datetime(2026, 6, 16, 0, 0, tzinfo=UTC))
        assert abs(late[0] - early[0]) < 0.01


class TestAqiCompositeRisk:
    def test_all_none_returns_none(self):
        score, level = aqi_composite_risk(None, None, None, None, None)
        assert score is None
        assert level is None

    def test_clean_air_is_good(self):
        score, level = aqi_composite_risk(pm2_5=2.0, pm10=5.0, o3=10.0, no2=5.0, so2=1.0)
        assert level == "good"

    def test_high_pollution_is_worse_than_low(self):
        low_score, _ = aqi_composite_risk(pm2_5=2.0, pm10=5.0, o3=10.0, no2=5.0, so2=1.0)
        high_score, _ = aqi_composite_risk(pm2_5=150.0, pm10=300.0, o3=150.0, no2=150.0, so2=100.0)
        assert high_score > low_score

    def test_partial_data_still_computes(self):
        score, level = aqi_composite_risk(pm2_5=10.0, pm10=None, o3=None, no2=None, so2=None)
        assert score is not None
        assert level is not None


class TestStormIndicator:
    def test_falling_pressure_and_high_wind_is_storm(self):
        assert storm_indicator(-1.5, 40.0, 0.0) is True

    def test_falling_pressure_and_rain_is_storm(self):
        assert storm_indicator(-1.2, 5.0, 5.0) is True

    def test_stable_pressure_is_not_storm(self):
        assert storm_indicator(0.1, 40.0, 5.0) is False

    def test_falling_pressure_but_calm_is_not_storm(self):
        assert storm_indicator(-1.5, 5.0, 0.0) is False

    def test_missing_pressure_trend_returns_none(self):
        assert storm_indicator(None, 40.0, 5.0) is None
