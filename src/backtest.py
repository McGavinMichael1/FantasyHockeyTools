# Spot-check backtest for the pickup model.
#
# Replays the 2025-26 season at several as-of dates. That season is genuinely
# held out (the model trains on <=2022 and validates on 2023), and every
# feature in buildRollingFeatures only looks backward, so features can be
# built once on the full data and sliced at any date without leakage.
#
# At each date: take every player's latest game state up to that date, score
# with the saved model, and grade the ranking against the player's ACTUAL next
# 5 games -- the same horizon the is_heating_up label was trained on.
#
# Historical Yahoo rosters can't be reconstructed (they changed month to
# month), so "free agent" is approximated by dropping the top players by
# season scoring pace to date -- those would be rostered in any real league --
# plus anyone who scored like a top-150 player the PRIOR season. The second
# filter keeps slow-starting stars (drafted, never on waivers) out of the pool
# early in the year, before their current-season pace reflects who they are.

import pandas as pd

from src.features import mlFeatures
from src.models import pickups as pickupModel

SEASON = 2025
DEFAULT_DATES = [20251101, 20251201, 20260101, 20260201, 20260301]

LOOKAHEAD_GAMES = 5       # label horizon the model was trained on
MIN_LOOKAHEAD_GAMES = 3   # need at least this many future games to grade
MIN_SEASON_GAMES = 5      # games played by the as-of date to be rankable
MAX_DAYS_IDLE = 10        # skip players not dressing (injured / sent down)
ROSTER_PROXY_CUTOFF = 150 # top-N by season pace ~= already rostered
DRAFT_PROXY_CUTOFF = 150  # top-N by PRIOR-season FP/g ~= drafted, never a FA
PRIOR_MIN_GAMES = 40      # prior-season sample needed to count as a proven star
HOT_PERCENTILE = 0.75     # mirrors the training label's hot_quantile

# The fantasy press's consensus best waiver adds of 2025-26, with roughly when
# they got hot. A sane ranking should surface each of them around that time.
KNOWN_PICKUPS = {
    'Nick Schmaltz': 'hot Oct-Nov, finished 33G/74P',
    'Cutter Gauthier': '11 goals in first 13 games',
    'Matthew Schaefer': 'rookie D, hot from opening night',
    'Beckett Sennecke': 'rookie, 5% rostered in week 2',
    'Evgeni Malkin': 'hot start, 61P in 56 GP',
    'Trevor Zegras': 'hot start in PHI',
    'Brock Nelson': 'ramped up from late November',
    'Darren Raddysh': 'Hedman injury opened PP1 mid-season, 70P',
    'Anthony Mantha': '~0.8 P/G all season',
    'Jared McCann': 'early January add',
}


def loadFeatureData():
    df = mlFeatures.loadMoneyPuckData()
    df = mlFeatures.buildRollingFeatures(df)
    prior = df[df['season'] == SEASON - 1]
    prior_fp = prior.groupby('playerId').agg(
        gp=('gameId', 'nunique'), fp=('game_fantasy_points', 'mean'))
    prior_fp = prior_fp[prior_fp['gp'] >= PRIOR_MIN_GAMES]
    drafted = set(prior_fp.nlargest(DRAFT_PROXY_CUTOFF, 'fp').index)
    return df[df['season'] == SEASON].copy(), drafted


def spotCheck(season_df, drafted, as_of_date, top_n=15):
    past = season_df[season_df['gameDate'] <= as_of_date]
    future = season_df[season_df['gameDate'] > as_of_date]

    state = past.groupby('playerId').last().reset_index()
    state['seasonGames'] = state['playerId'].map(past.groupby('playerId').size())

    as_of_ts = pd.to_datetime(str(as_of_date), format='%Y%m%d')
    last_game = pd.to_datetime(state['gameDate'].astype(int).astype(str), format='%Y%m%d')
    state['daysIdle'] = (as_of_ts - last_game).dt.days

    active = state[(state['seasonGames'] >= MIN_SEASON_GAMES)
                   & (state['daysIdle'] <= MAX_DAYS_IDLE)].copy()

    active['ml_score'] = pickupModel.predict(active)

    # Ground truth: mean fantasy points over each player's next 5 games,
    # ranked against the rest of the active pool (like the training label).
    nxt = future.sort_values(['playerId', 'gameDate']).groupby('playerId').head(LOOKAHEAD_GAMES)
    outcome = nxt.groupby('playerId').agg(
        next_fp=('game_fantasy_points', 'mean'),
        next_games=('gameId', 'nunique'),
    )
    active = active.merge(outcome, on='playerId', how='left')
    graded = active[active['next_games'] >= MIN_LOOKAHEAD_GAMES].copy()
    graded['next_pctile'] = graded['next_fp'].rank(pct=True)
    graded['hit'] = graded['next_pctile'] >= HOT_PERCENTILE

    # Roster proxy: the best season performers to date would not be free
    # agents, and neither would last season's proven stars (drafted).
    graded['seasonRank'] = graded['season_avg_so_far'].rank(ascending=False)
    pool = graded[(graded['seasonRank'] > ROSTER_PROXY_CUTOFF)
                  & ~graded['playerId'].isin(drafted)]
    pool = pool.sort_values('ml_score', ascending=False).reset_index(drop=True)

    date_str = as_of_ts.date().isoformat()
    print(f"\n{'=' * 78}")
    print(f"=== Spot check @ {date_str}  "
          f"(free-agent pool: {len(pool)} of {len(graded)} graded players) ===")

    top = pool.head(top_n)
    cols = ['name', 'position', 'ml_score', 'season_avg_so_far', 'next_fp', 'next_pctile', 'hit']
    print(top[cols].round(3).to_string(index=False))

    # Did the model's top-N actually heat up more often than chance (25% by
    # construction) and more often than just chasing recent scoring?
    naive = pool.sort_values('rolling_10_game_fantasy_points', ascending=False).head(top_n)
    print(f"\nTop-{top_n} hit rate: model {top['hit'].mean():.0%} | "
          f"last-10-FP baseline {naive['hit'].mean():.0%} | "
          f"pool base rate {pool['hit'].mean():.0%}")

    print("\nKnown 2025-26 waiver gems on this date:")
    for player, note in KNOWN_PICKUPS.items():
        row = graded[graded['name'] == player]
        if row.empty:
            print(f"  {player:18s} not rankable (too few games / idle)  [{note}]")
            continue
        r = row.iloc[0]
        pool_row = pool[pool['name'] == player]
        if not pool_row.empty:
            where = f"FA rank {pool_row.index[0] + 1}/{len(pool)}"
        elif r['playerId'] in drafted:
            where = "drafted by proxy (prior-season star)"
        else:
            where = f"rostered by proxy (#{int(r['seasonRank'])} season pace)"
        print(f"  {player:18s} {where:32s} ml={r['ml_score']:.3f} "
              f"next5={r['next_fp']:.1f} FP/g  [{note}]")

    return pool


def runSpotChecks(dates=None, top_n=15):
    dates = dates or DEFAULT_DATES
    season_df, drafted = loadFeatureData()
    for as_of_date in dates:
        spotCheck(season_df, drafted, as_of_date, top_n=top_n)
