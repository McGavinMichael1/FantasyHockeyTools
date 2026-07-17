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

def rankFreeAgents(pickup_stats_df, players_df, rostered_nhle_ids):
    """Heuristic free-agent ranking over MoneyPuck-derived pickup stats
    (moneypuck.buildPickupStats output). players_df is the NHL roster
    identity frame; players missing from it (e.g. recently moved) fall back
    to MoneyPuck's name/position instead of being dropped.
    """
    df = pd.merge(pickup_stats_df, players_df,
                  left_on='playerId', right_on='id', how='left')
    df['full_name'] = df['full_name'].fillna(df['name'])
    df['positionCode'] = df['positionCode'].fillna(df['position'])

    df['weighted_score'] = 0.6 * df['season_ppg'] + 0.4 * df['last5_fantasyPoints']

    df = df[df['positionCode'] != 'G']  # remove goalies
    df = df[~df['playerId'].isin(rostered_nhle_ids)]  # remove rostered players
    df = df[df['gamesPlayed'] >= 5]  # remove small sample size players

    return df.sort_values('weighted_score', ascending=False)

