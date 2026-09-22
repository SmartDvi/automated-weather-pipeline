from datetime import UTC, datetime, timedelta

import pandas as pd

from weatherml.ml.dataset import FEATURE_COLUMNS, build_supervised_frame, time_ordered_split


def _features_frame(times: list[datetime]) -> pd.DataFrame:
    data = {"feature_time": times}
    for col in FEATURE_COLUMNS:
        data[col] = [1.0] * len(times)
    return pd.DataFrame(data)


def _obs_frame(times_and_temps: list[tuple[datetime, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_time": [t for t, _ in times_and_temps],
            "target_temp_c": [v for _, v in times_and_temps],
        }
    )


def test_matches_observation_nearest_horizon_offset():
    base = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    features = _features_frame([base])
    obs = _obs_frame([(base, 20.0), (base + timedelta(hours=1), 25.0)])
    result = build_supervised_frame(features, obs, horizon_hours=1)
    assert len(result) == 1
    assert result.iloc[0]["target_temp_c"] == 25.0


def test_drops_rows_with_no_match_within_tolerance():
    base = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    features = _features_frame([base])
    # only observation is far outside the +/-12min tolerance around target_time
    obs = _obs_frame([(base + timedelta(hours=2), 30.0)])
    result = build_supervised_frame(features, obs, horizon_hours=1)
    assert result.empty


def test_never_matches_an_observation_before_feature_time():
    """The no-leakage property for training data: even if an earlier
    observation is numerically closer in absolute time due to sparse data,
    the label must come from at or after feature_time (the merge_asof
    target_time is feature_time + horizon, and tolerance is far smaller than
    the horizon here, so an earlier row cannot possibly win the match).
    """
    base = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    features = _features_frame([base])
    obs = _obs_frame(
        [
            (base - timedelta(minutes=1), 999.0),  # before feature_time - must never be the label
            (base + timedelta(hours=1), 25.0),
        ]
    )
    result = build_supervised_frame(features, obs, horizon_hours=1)
    assert result.iloc[0]["target_temp_c"] == 25.0


def test_empty_inputs_return_empty_frame():
    assert build_supervised_frame(pd.DataFrame(), pd.DataFrame(), horizon_hours=1).empty


class TestTimeOrderedSplit:
    def test_splits_without_shuffling(self):
        times = [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(10)]
        df = pd.DataFrame({"feature_time": times, "value": range(10)})
        train, test = time_ordered_split(df, test_size=0.2)
        assert len(train) == 8
        assert len(test) == 2
        assert train["feature_time"].max() < test["feature_time"].min()

    def test_handles_unsorted_input(self):
        times = [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in [3, 1, 4, 0, 2]]
        df = pd.DataFrame({"feature_time": times, "value": range(5)})
        train, test = time_ordered_split(df, test_size=0.2)
        assert train["feature_time"].max() < test["feature_time"].min()
