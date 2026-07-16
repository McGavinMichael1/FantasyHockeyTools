# Goalie draft pipeline: the merged goalie-season table and its draft features.
#
# MoneyPuck goalie data is shot/xGoals data only -- no W/L/SO/GS -- so fantasy
# points come from NHL API season records (src/dataProcessing.py) merged in.
# MoneyPuck contributes the skill features (gsax, expected save%).

import pandas as pd

from src import fantasyPoints


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
