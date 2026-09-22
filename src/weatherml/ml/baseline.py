import mlflow.pyfunc
import pandas as pd


class PersistenceModel(mlflow.pyfunc.PythonModel):
    """Naive forecast: predicts temp(t+h) = temp(t). This is the baseline
    every candidate model must beat (see ml/registry.py::decide_promotion) —
    a model that can't outperform "assume nothing changes" has no business
    being registered, regardless of how good its own metrics look in
    isolation.
    """

    def predict(self, context, model_input: pd.DataFrame, params=None) -> pd.Series:
        return model_input["current_temp_c"]
