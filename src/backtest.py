# Spot-check backtest for the pickup model.
#
# Replays the 2025-26 season at several as-of dates. That season is genuinely
# held out (the model trains on <=2022 and validates on 2023), and every
# feature in buildRollingFeatures only looks backward, so features can be
# built once on the full data and sliced at any date without leakage.
#
# At each date: take every player's latest game state up to that date, score
# with the saved model, and grade the ranking against the player's ACTUAL next
# 5 games -- the same horizon the next_5_avg regression target was trained on.
#
# Historical Yahoo rosters can't be reconstructed (they changed month to
# month), so "free agent" is approximated by dropping the top players by
# season scoring pace to date -- those would be rostered in any real league.
# Prior-season stars are deliberately NOT exempted: several KNOWN_PICKUPS
# (Malkin, Nelson, McCann, Schmaltz) were genuinely on waivers despite strong
# prior seasons, so a prior-season filter would hide the cases being graded.

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
HOT_PERCENTILE = 0.75     # mirrors the training label's hot_quantile
PICKUPS_PER_DATE = 5      # simulated adds per date, removed from later pools

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
    return df[df['season'] == SEASON].copy()


def spotCheck(season_df, as_of_date, top_n=15,
              model_taken=frozenset(), naive_taken=frozenset()):
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
    # agents.
    graded['seasonRank'] = graded['season_avg_so_far'].rank(ascending=False)
    fa = graded[graded['seasonRank'] > ROSTER_PROXY_CUTOFF]

    # Pseudo-simulation: players recommended at an earlier date are treated as
    # picked up and off the wire. Model and chaser each shrink their own pool,
    # so each strategy is replayed independently.
    pool = fa[~fa['playerId'].isin(model_taken)]
    pool = pool.sort_values('ml_score', ascending=False).reset_index(drop=True)
    naive_pool = fa[~fa['playerId'].isin(naive_taken)]
    naive_pool = naive_pool.sort_values('rolling_10_game_fantasy_points', ascending=False).reset_index(drop=True)

    date_str = as_of_ts.date().isoformat()
    sim_note = f"; {len(model_taken)} sim pickups excluded" if model_taken else ""
    print(f"\n{'=' * 78}")
    print(f"=== Spot check @ {date_str}  "
          f"(free-agent pool: {len(pool)} of {len(graded)} graded players{sim_note}) ===")

    top = pool.head(top_n)
    cols = ['name', 'position', 'ml_score', 'season_avg_so_far', 'next_fp', 'next_pctile', 'hit']
    print(top[cols].round(3).to_string(index=False))

    # Did the model's top-N actually heat up more often than chance (25% by
    # construction) and more often than just chasing recent scoring?
    naive = naive_pool.head(top_n)
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
        if r['playerId'] in model_taken:
            where = "picked up at an earlier sim date"
        elif not pool_row.empty:
            where = f"FA rank {pool_row.index[0] + 1}/{len(pool)}"
        else:
            where = f"rostered by proxy (#{int(r['seasonRank'])} season pace)"
        print(f"  {player:18s} {where:32s} ml={r['ml_score']:.3f} "
              f"next5={r['next_fp']:.1f} FP/g  [{note}]")

    picks = pool.head(PICKUPS_PER_DATE).assign(as_of=date_str)
    naive_picks = naive_pool.head(PICKUPS_PER_DATE).assign(as_of=date_str)
    return picks, naive_picks


def runSpotChecks(dates=None, top_n=15):
    """Replay the season in date order as a pseudo-simulation: the top
    PICKUPS_PER_DATE recommendations at each date are treated as picked up and
    removed from the free-agent pool at every later date."""
    dates = sorted(dates or DEFAULT_DATES)
    season_df = loadFeatureData()
    model_taken, naive_taken = set(), set()
    model_adds, naive_adds = [], []
    for as_of_date in dates:
        picks, naive_picks = spotCheck(season_df, as_of_date, top_n=top_n,
                                       model_taken=model_taken,
                                       naive_taken=naive_taken)
        model_taken.update(picks['playerId'])
        naive_taken.update(naive_picks['playerId'])
        model_adds.append(picks)
        naive_adds.append(naive_picks)

    model_adds = pd.concat(model_adds, ignore_index=True)
    naive_adds = pd.concat(naive_adds, ignore_index=True)
    print(f"\n{'=' * 78}")
    print(f"=== Season simulation: the model's top-{PICKUPS_PER_DATE} adds at each date ===")
    cols = ['as_of', 'name', 'position', 'ml_score', 'next_fp', 'next_pctile', 'hit']
    print(model_adds[cols].round(3).to_string(index=False))
    print(f"\nSimulated adds ({len(model_adds)} per strategy): "
          f"model hit rate {model_adds['hit'].mean():.0%}, "
          f"avg realized next-5 {model_adds['next_fp'].mean():.2f} FP/g | "
          f"last-10-FP chaser hit rate {naive_adds['hit'].mean():.0%}, "
          f"avg {naive_adds['next_fp'].mean():.2f} FP/g")
