# Features specific to the mid-season pickup task.
# Pickup predictions care about short-term value (next 2-4 weeks), so features
# here should capture recent form, upcoming schedule, and role changes.
#
# Examples of what belongs here:
#   - Rolling fantasy points (last 7, 14, 30 days)
#   - Ice time trend (increasing / decreasing)
#   - Upcoming opponent strength
#   - Games remaining in next 2 weeks
#   - Power play opportunity trend

import pandas as pd


def build_pickup_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Takes the base player DataFrame (with shared features already applied)
    and adds pickup-specific features.
    Returns a new DataFrame with the added columns.
    """
    # TODO: implement pickup feature engineering
    raise NotImplementedError
