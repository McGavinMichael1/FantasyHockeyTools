# Features shared across all prediction tasks.
# These are derived from the base player DataFrame and can be reused
# by both draft and pickup models.
#
# Examples of what belongs here:
#   - Position encoding
#   - Team encoding
#   - Career games played
#   - Fantasy points per game (season total)

import pandas as pd
from src import keepers, moneypuck


def build_shared_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Takes the base player DataFrame and adds features common to all tasks.
    Returns a new DataFrame with the added columns.
    """
    # TODO: implement shared feature engineering
    raise NotImplementedError


def select_matrix(df, feature_cols, label_col=None):
    """Slice an engineered DataFrame into the (X, y) contract every model uses.

    Deliberately dumb: it only selects columns. Each task decides *which*
    columns are features (an allowlist -- a column nobody named is simply
    absent, never silently fed to a model), and any per-model preprocessing
    (imputation, scaling) stays in the model module. `y` is None when
    `label_col` is missing from `df`, which is the predict-time case where the
    rows have no label yet.
    """
    X = df[feature_cols]
    y = df[label_col] if label_col and label_col in df.columns else None
    return X, y
