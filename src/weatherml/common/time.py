from datetime import UTC, datetime, timedelta


def epoch_and_offset_to_utc(localtime_epoch: int, utc_offset_hours: float) -> datetime:
    """Weatherstack's `location.localtime_epoch` is NOT a true Unix UTC
    epoch, despite the name suggesting otherwise. Empirically (verified
    against live responses for all 5 seeded locations spanning offsets from
    -4 to +10), it's the LOCAL wall-clock time encoded as if it were UTC:

        localtime_epoch == true_utc_epoch + utc_offset_hours * 3600

    So naively doing fromtimestamp(localtime_epoch, tz=UTC) reproduces the
    correct local clock digits but at the WRONG absolute instant, off by
    exactly utc_offset_hours. Recovering true UTC requires subtracting the
    offset back out.
    """
    true_utc_epoch = localtime_epoch - utc_offset_hours * 3600
    return datetime.fromtimestamp(true_utc_epoch, tz=UTC)


def floor_to_interval(dt: datetime, minutes: int) -> datetime:
    """Floor a timestamp to the nearest preceding `minutes` boundary, e.g. for
    bucketing observations into 5-minute ingestion slots.
    """
    discard = timedelta(
        minutes=dt.minute % minutes,
        seconds=dt.second,
        microseconds=dt.microsecond,
    )
    return dt - discard
