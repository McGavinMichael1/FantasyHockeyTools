# Features specific to the draft analysis task.
# Draft predictions care about season-long value, so features here
# should reflect a player's sustained ceiling and floor over a full season.
#
# Examples of what belongs here:
#   - Age and career trajectory
#   - Historical season totals
#   - Team powerplay usage trends
#   - Contract year / motivation factors (if data available)

import pandas as pd


def build_draft_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Takes the base player DataFrame (with shared features already applied)
    and adds draft-specific features.
    Returns a new DataFrame with the added columns.
    """
    # TODO: implement draft feature engineering
    raise NotImplementedError
