# Goalie draft pipeline: the merged goalie-season table and its draft features.
#
# MoneyPuck goalie data is shot/xGoals data only -- no W/L/SO/GS -- so fantasy
# points come from NHL API season records (src/dataProcessing.py) merged in.
# MoneyPuck contributes the skill features (gsax, expected save%).

import pandas as pd

from src import fantasyPoints
from src.features import shared


def build_goalie_seasons(mp_seasons: pd.DataFrame,
                         nhl_seasons: pd.DataFrame) -> pd.DataFrame:
    """One scored row per goalie-season: MoneyPuck skill + NHL API record.

    Inner merge on (playerId, season): a row without an NHL record has no
    W/L/SO and cannot be scored. Callers report the hit rate (GATE G1).
    `losses` stays the NHL regulation-only field -- owner confirmed 2026-07-16
    that OT/SO losses are not losses in this league; never add otLosses.
    """
    nhl = nhl_seasons.copy()
    nhl['saves'] = nhl['shotsAgainst'] - nhl['goalsAgainst']
    merged = mp_seasons.merge(nhl, on=['playerId', 'season'], how='inner')
    merged = merged.rename(columns={'name': 'full_name'})
    merged['position'] = 'G'
    merged['fantasyPoints'] = merged.apply(fantasyPoints.calculateGoaliePoints, axis=1)
    merged['fpPerGame'] = (merged['fantasyPoints']
                           / merged['gamesPlayed'].where(merged['gamesPlayed'] > 0))
    merged['gsax'] = merged['xGoals'] - merged['goals']
    merged['save_pct'] = 1 - merged['goals'] / merged['ongoal'].where(merged['ongoal'] > 0)
    merged['xsave_delta'] = merged['gsax'] / merged['ongoal'].where(merged['ongoal'] > 0)
    return merged


def build_goalie_features(goalie_seasons: pd.DataFrame) -> pd.DataFrame:
    """Draft features from the goalie_seasons table.

    Same leakage discipline as src/features/draft.py (GATE G2): each row IS a
    concluded season, so own-season columns are legitimate features with no
    shift; only the target shifts, masked to consecutive seasons; every lag is
    groupby(playerId)-scoped. No position one-hots -- every row is a G.
    """
    df = goalie_seasons.sort_values(['playerId', 'season']).copy()
    df['career_games'] = df.groupby('playerId')['gamesPlayed'].cumsum()
    # workload is the dominant goalie fantasy signal (starter vs backup)
    df['gs_share'] = df['gamesStarted'] / 82
    df['gsax_per60'] = (df['gsax'] / df['icetime'].where(df['icetime'] > 0)) * 3600

    g = df.groupby('playerId')
    df['fp_delta'] = g['fpPerGame'].diff()
    # 50/30/20 weighted recency, renormalized when history is short -- the
    # same scheme as the skater fp_w3. gp_w3 feeds the projected-GP heuristic.
    for col, out in (('fpPerGame', 'fp_w3'), ('gamesPlayed', 'gp_w3')):
        w = pd.concat([df[col] * 0.5,
                       g[col].shift(1) * 0.3,
                       g[col].shift(2) * 0.2], axis=1)
        weights_present = w.notna().mul([0.5, 0.3, 0.2]).sum(axis=1)
        df[out] = w.sum(axis=1) / weights_present

    df = shared.add_age_at_season_start(df)

    g = df.groupby('playerId')  # re-group: the merge above changed df
    next_season = g['season'].shift(-1)
    df['target_fpPerGame'] = g['fpPerGame'].shift(-1).where(
        next_season == df['season'] + 1)
    df['target_gamesPlayed'] = g['gamesPlayed'].shift(-1).where(
        next_season == df['season'] + 1)
    return df
