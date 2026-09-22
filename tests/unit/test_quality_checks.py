from datetime import UTC, datetime, timedelta

from weatherml.quality.checks import check_freshness, check_required_fields, check_value_ranges


class TestFreshness:
    def test_no_observation_is_critical(self):
        result = check_freshness(None, datetime.now(UTC), 15)
        assert result.passed is False
        assert result.severity == "critical"

    def test_recent_observation_passes(self):
        now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        result = check_freshness(now - timedelta(minutes=3), now, 15)
        assert result.passed is True
        assert result.severity == "info"

    def test_moderately_stale_is_warning(self):
        now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        result = check_freshness(now - timedelta(minutes=20), now, 15)
        assert result.passed is False
        assert result.severity == "warning"

    def test_very_stale_is_critical(self):
        now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        result = check_freshness(now - timedelta(hours=2), now, 15)
        assert result.passed is False
        assert result.severity == "critical"


class TestValueRanges:
    def test_plausible_values_pass(self):
        result = check_value_ranges(20.0, 60.0, 1013.0)
        assert result.passed is True

    def test_impossible_temperature_fails(self):
        result = check_value_ranges(500.0, 60.0, 1013.0)
        assert result.passed is False
        assert result.severity == "critical"

    def test_impossible_humidity_fails(self):
        result = check_value_ranges(20.0, 150.0, 1013.0)
        assert result.passed is False

    def test_none_values_are_ignored_not_flagged(self):
        result = check_value_ranges(None, None, None)
        assert result.passed is True


class TestRequiredFields:
    def test_all_present_passes(self):
        result = check_required_fields(20.0, 60.0, 1013.0)
        assert result.passed is True

    def test_missing_field_is_warning_not_critical(self):
        result = check_required_fields(None, 60.0, 1013.0)
        assert result.passed is False
        assert result.severity == "warning"
        assert "temperature_c" in result.details["missing"]
