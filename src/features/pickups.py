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

def rankFreeAgents(stats_current_df, stats_last5_df, players_df, rostered_nhle_ids):
    df = pd.merge(stats_current_df, stats_last5_df, on='player_id', suffixes=('_season', '_last5'))
    df = pd.merge(df, players_df, left_on='player_id', right_on='id')

    df['season_ppg'] = df['fantasyPoints_season'] / df['gamesPlayed'].replace(0, 1)

    df['weighted_score'] = 0.6 * df['season_ppg'] + 0.4 * df['fantasyPoints_last5']

    df = df[df['positionCode'] != 'G']  # remove goalies
    df = df[~df['player_id'].isin(rostered_nhle_ids)]  # remove rostered players
    df = df[df['gamesPlayed'] >= 5]  # remove small sample size players

    return df.sort_values('weighted_score', ascending=False)

