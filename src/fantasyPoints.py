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


def moneypuckGamePoints(games_df):
    """League fantasy points from MoneyPuck game logs.

    games_df must contain ALL situation rows ('all', '5on4', '4on5', ...).
    Returns one row per player-game (the 'all' rows) with powerPlayPoints,
    shorthandedPoints, and fantasyPoints columns added.
    PPP = points in 5on4 rows, SHP = points in 4on5 rows (5on3 lands in
    'other' — slight undercount, accepted).
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