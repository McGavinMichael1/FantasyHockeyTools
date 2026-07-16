# League scoring weights for skaters — the single source of truth.
# GWG and plusMinus are only available from the NHL API path; the MoneyPuck
# path (moneypuckGamePoints) omits them, a documented ~5% approximation.
SKATER_WEIGHTS = {
    'goals': 3,
    'assists': 2,
    'plusMinus': 0.5,
    'gameWinningGoals': 1,
    'powerPlayPoints': 1,
    'shorthandedPoints': 1,
    'shotsOnGoal': 0.15,
    'hits': 0.15,
    'blocks': 0.35,
}


def calculateSkaterPoints(stats):
    points = 0
    points += stats.get('goals', 0) * SKATER_WEIGHTS['goals']
    points += stats.get('assists', 0) * SKATER_WEIGHTS['assists']
    points += stats.get('plusMinus', 0) * SKATER_WEIGHTS['plusMinus']
    points += stats.get('gameWinningGoals', 0) * SKATER_WEIGHTS['gameWinningGoals']
    points += stats.get('powerPlayPoints', 0) * SKATER_WEIGHTS['powerPlayPoints']
    points += stats.get('shorthandedPoints', 0) * SKATER_WEIGHTS['shorthandedPoints']
    points += stats.get('shots', 0) * SKATER_WEIGHTS['shotsOnGoal']
    return points


# League scoring weights for goalies — the single source of truth, same
# discipline as SKATER_WEIGHTS. `losses` is regulation-only (owner confirmed
# 2026-07-16): this league does not record OT/SO losses as losses, so use
# the NHL API `losses` field as-is and never add otLosses.
GOALIE_WEIGHTS = {
    'gamesStarted': 0.75,
    'wins': 2.5,
    'losses': -1,
    'goalsAgainst': -0.5,
    'saves': 0.15,
    'shutouts': 3,
}


def calculateGoaliePoints(stats):
    """League fantasy points for one goalie stat line (dict or pandas Series).

    Keys are NHL-API field names; `saves` is derived upstream as
    shotsAgainst - goalsAgainst. Missing keys count as zero.
    """
    points = 0
    for stat, weight in GOALIE_WEIGHTS.items():
        points += (stats.get(stat, 0) or 0) * weight
    return points


def moneypuckGamePoints(games_df):
    """League fantasy points from MoneyPuck game logs.

    games_df must contain ALL situation rows ('all', '5on4', '4on5', ...).
    Returns one row per player-game (the 'all' rows) with powerPlayPoints,
    powerPlayGoals, powerPlayAssists, shorthandedPoints, and fantasyPoints
    columns added.
    PPP = points in 5on4 rows, SHP = points in 4on5 rows (5on3 lands in
    'other' — slight undercount, accepted).
    powerPlayGoals / powerPlayAssists carry the 5on4 scoring breakdown so
    draft features can value PP production in fantasy units (a PP goal is
    worth 3+1, a PP assist 2+1), not just the raw PPP bonus — see
    src/features/draft.py PP_share.
    """
    result = games_df[games_df['situation'] == 'all'].copy()
    for situation, col in (('5on4', 'powerPlayPoints'), ('4on5', 'shorthandedPoints')):
        points = (games_df[games_df['situation'] == situation]
                  .groupby(['playerId', 'gameId'])['I_F_points']
                  .sum()
                  .rename(col)
                  .reset_index())
        result = result.merge(points, on=['playerId', 'gameId'], how='left')
        result[col] = result[col].fillna(0)

    pp = games_df[games_df['situation'] == '5on4'].copy()
    pp['ppAssists'] = pp['I_F_primaryAssists'] + pp['I_F_secondaryAssists']
    pp_breakdown = (pp.groupby(['playerId', 'gameId'])
                    .agg(powerPlayGoals=('I_F_goals', 'sum'),
                         powerPlayAssists=('ppAssists', 'sum'))
                    .reset_index())
    result = result.merge(pp_breakdown, on=['playerId', 'gameId'], how='left')
    result[['powerPlayGoals', 'powerPlayAssists']] = (
        result[['powerPlayGoals', 'powerPlayAssists']].fillna(0))

    result['fantasyPoints'] = (
        result['I_F_goals'] * SKATER_WEIGHTS['goals']
        + (result['I_F_primaryAssists'] + result['I_F_secondaryAssists']) * SKATER_WEIGHTS['assists']
        + result['I_F_shotsOnGoal'] * SKATER_WEIGHTS['shotsOnGoal']
        + result['I_F_hits'] * SKATER_WEIGHTS['hits']
        + result['shotsBlockedByPlayer'] * SKATER_WEIGHTS['blocks']
        + result['powerPlayPoints'] * SKATER_WEIGHTS['powerPlayPoints']
        + result['shorthandedPoints'] * SKATER_WEIGHTS['shorthandedPoints']
    )
    return result