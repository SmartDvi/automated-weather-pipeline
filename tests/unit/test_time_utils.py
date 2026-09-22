"""Regression tests for the localtime_epoch conversion bug found during live
verification: weatherstack's `location.localtime_epoch` is local wall-clock
time encoded as if it were UTC, not a true Unix UTC epoch. These fixtures
are the exact (rounded) values observed from live API responses across 5
locations spanning offsets from -4 to +10.
"""

from datetime import UTC, datetime

from weatherml.common.time import epoch_and_offset_to_utc, floor_to_interval


def test_epoch_and_offset_negative_offset_new_york():
    # true UTC now ~= 2026-09-22 14:47 UTC; NY is UTC-4 in September (EDT).
    # localtime_epoch encodes 2026-09-22 10:47 (local) as if it were UTC.
    localtime_epoch = int(datetime(2026, 9, 22, 10, 47, tzinfo=UTC).timestamp())
    result = epoch_and_offset_to_utc(localtime_epoch, -4.0)
    assert result == datetime(2026, 9, 22, 14, 47, tzinfo=UTC)


def test_epoch_and_offset_positive_offset_tokyo():
    # Tokyo is UTC+9; localtime_epoch encodes 23:47 local as if it were UTC.
    localtime_epoch = int(datetime(2026, 9, 22, 23, 47, tzinfo=UTC).timestamp())
    result = epoch_and_offset_to_utc(localtime_epoch, 9.0)
    assert result == datetime(2026, 9, 22, 14, 47, tzinfo=UTC)


def test_epoch_and_offset_zero_offset_is_identity():
    localtime_epoch = int(datetime(2026, 9, 22, 14, 47, tzinfo=UTC).timestamp())
    result = epoch_and_offset_to_utc(localtime_epoch, 0.0)
    assert result == datetime(2026, 9, 22, 14, 47, tzinfo=UTC)


def test_floor_to_interval_rounds_down_to_5_minutes():
    dt = datetime(2026, 9, 22, 14, 48, 37, tzinfo=UTC)
    assert floor_to_interval(dt, 5) == datetime(2026, 9, 22, 14, 45, tzinfo=UTC)


def test_floor_to_interval_already_on_boundary():
    dt = datetime(2026, 9, 22, 14, 45, 0, tzinfo=UTC)
    assert floor_to_interval(dt, 5) == dt
