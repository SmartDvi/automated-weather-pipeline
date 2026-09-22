from weatherml.ml.evaluate import (
    evaluate_predictions,
    mean_absolute_error,
    mean_absolute_percentage_error,
    root_mean_squared_error,
)


def test_mae_perfect_predictions_is_zero():
    assert mean_absolute_error([1, 2, 3], [1, 2, 3]) == 0.0


def test_mae_computes_average_absolute_difference():
    assert mean_absolute_error([10, 20], [12, 18]) == 2.0


def test_rmse_penalizes_large_errors_more_than_mae():
    y_true = [0, 0, 0, 10]
    y_pred = [0, 0, 0, 0]
    mae = mean_absolute_error(y_true, y_pred)
    rmse = root_mean_squared_error(y_true, y_pred)
    assert rmse > mae


def test_mape_guards_divide_by_zero():
    # a zero true value must not raise or produce inf/nan from that point
    result = mean_absolute_percentage_error([0, 10], [1, 11])
    assert result == 10.0  # only the second point (10 -> 11) contributes


def test_mape_all_zero_returns_nan():
    import math

    result = mean_absolute_percentage_error([0, 0], [1, 1])
    assert math.isnan(result)


def test_evaluate_predictions_returns_all_three_metrics():
    result = evaluate_predictions([10, 20, 30], [11, 19, 31])
    assert set(result.keys()) == {"mae", "rmse", "mape"}
    assert all(v >= 0 for v in result.values())
