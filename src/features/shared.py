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


def build_shared_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Takes the base player DataFrame and adds features common to all tasks.
    Returns a new DataFrame with the added columns.
    """
    # TODO: implement shared feature engineering
    raise NotImplementedError
