import numpy as np


def mean_absolute_error(y_true, y_pred) -> float:
    return float(np.mean(np.abs(np.asarray(y_true, dtype=float) - np.asarray(y_pred, dtype=float))))


def root_mean_squared_error(y_true, y_pred) -> float:
    diff = np.asarray(y_true, dtype=float) - np.asarray(y_pred, dtype=float)
    return float(np.sqrt(np.mean(diff**2)))


def mean_absolute_percentage_error(y_true, y_pred) -> float:
    """Guards div-by-zero (temperature crossing 0C makes raw MAPE unstable/
    undefined) by masking those points; reported as a supplementary metric
    alongside MAE/RMSE, never the sole promotion criterion, for that reason.
    """
    y_true_arr = np.asarray(y_true, dtype=float)
    y_pred_arr = np.asarray(y_pred, dtype=float)
    mask = y_true_arr != 0
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((y_true_arr[mask] - y_pred_arr[mask]) / y_true_arr[mask])) * 100)


def evaluate_predictions(y_true, y_pred) -> dict[str, float]:
    return {
        "mae": mean_absolute_error(y_true, y_pred),
        "rmse": root_mean_squared_error(y_true, y_pred),
        "mape": mean_absolute_percentage_error(y_true, y_pred),
    }
