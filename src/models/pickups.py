# Mid-season pickup model: train, save, load, and predict short-term fantasy value.
#
# All model modules expose the same interface so the UI and any calling code
# doesn't need to know which model type is underneath:
#   train(df)    -> fits and saves the model
#   predict(df)  -> loads the model and returns predictions
#   load()       -> returns the saved model object
#   save(model)  -> persists the model to disk

import pandas as pd

MODEL_PATH = "models/pickups/model.pkl"


def train(df: pd.DataFrame):
    """Train the pickup model on rolling window data and save it."""
    # TODO: define target variable (e.g. fantasy points over next 14 days)
    # TODO: select feature columns from df
    # TODO: train/validation split (time-based split — don't shuffle!)
    # TODO: fit model
    # TODO: evaluate and log metrics
    # TODO: call save(model)
    raise NotImplementedError


def predict(df: pd.DataFrame) -> pd.Series:
    """Load the saved model and return predicted short-term fantasy points."""
    # TODO: load model, select feature columns, return predictions
    raise NotImplementedError


def load():
    """Load and return the saved model object."""
    # TODO: unpickle from MODEL_PATH
    raise NotImplementedError


def save(model):
    """Persist the model object to MODEL_PATH."""
    # TODO: pickle model to MODEL_PATH
    raise NotImplementedError
