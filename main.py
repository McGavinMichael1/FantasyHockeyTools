import argparse
import json
import os

import pandas as pd

from src import backtest
from src import dataProcessing
from src import draft_explain
from src import fantasyPoints
from src import keeper
from src import keepers
from src import moneypuck
from src import yahooAPI
from src.features import draft as draftFeatures
from src.features import mlFeatures
from src.features import pickups
from src.models import cooling as coolingModel
from src.models import draft as draftModel
from src.models import pickups as pickupModel

CURRENT_SEASON = 2025  # MoneyPuck convention: 2025 = the 2025-26 season
KEEPER_RANKINGS_PATH = os.path.join('data', 'processed', 'keeper_rankings.csv')


def loadLabeledHistory():
    """Rolling features + next-5-game FP target on completed seasons."""
    df = mlFeatures.loadMoneyPuckData()
    df = mlFeatures.buildRollingFeatures(df)
    # current season has no future games to label — train on completed seasons
    historical_df = df[df['season'] <= 2024].copy()
    return mlFeatures.buildLabel(historical_df)


def trainPickups():
    historical_df = loadLabeledHistory()
    print("=== Training pickup (heating up) model ===")
    pickupModel.train(historical_df)
    print("=== Training cooling model ===")
    coolingModel.train(historical_df)


def latestGameState():
    """Most recent game-state row per current-season player with >= 20 GP."""
    import os
    import time

    cache_file = os.path.join('data', 'processed', 'current_players_features.csv')

    # Check if cache exists and is fresh (< 24 hours old)
    if os.path.exists(cache_file):
        age_hours = (time.time() - os.path.getmtime(cache_file)) / 3600
        if age_hours < 24:
            import pandas as pd
            print(f"Loading cached current player features ({age_hours:.1f}h old)")
            return pd.read_csv(cache_file)

    # Cache miss or stale - compute features
    print("Computing current player features (this may take 30-60 seconds)...")
    df = mlFeatures.loadMoneyPuckData()
    df = mlFeatures.buildRollingFeatures(df)
    current_df = df[df['season'] == CURRENT_SEASON].copy()
    games_played = current_df.groupby('playerId').size().reset_index(name='gamesPlayed')
    current_players = current_df.groupby('playerId').last().reset_index()
    current_players = current_players.merge(games_played, on='playerId')
    current_players = current_players[current_players['gamesPlayed'] >= 20]

    # Save to cache
    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
    current_players.to_csv(cache_file, index=False)
    print(f"Cached features to {cache_file}")

    return current_players


def runPickups():
    moneypuck.checkCurrentFreshness()

    # Heuristic ranker on NHL API data
    allPlayerData = dataProcessing.getAllPlayersWithCache()
    allPlayerData = dataProcessing.flattenPlayerNames(allPlayerData)
    stats_df = dataProcessing.getAllStatsWithCache(allPlayerData['id'])
    stats_df['fantasyPoints'] = stats_df.apply(lambda row: fantasyPoints.calculateSkaterPoints(row), axis=1)
    last5_df = dataProcessing.getAllLast5WithCache(allPlayerData['id'])
    last5_df['fantasyPoints'] = last5_df.apply(lambda row: fantasyPoints.calculateSkaterPoints(row), axis=1)

    # Try to get rostered players from Yahoo (optional)
    rostered_nhle_ids = set()
    try:
        lg = yahooAPI.getLeague()
        rostered_names = yahooAPI.getRosteredIds(lg)
        rostered_nhle_ids = yahooAPI.getRosteredNHLIds(rostered_names, allPlayerData)
        print(f"Yahoo API: Filtering out {len(rostered_nhle_ids)} rostered players")
    except FileNotFoundError as e:
        print(f"⚠️  Yahoo API disabled: {e}")
        print("   To enable, create oauth2.json with Yahoo OAuth credentials")
        print("   See: https://github.com/josuebrunel/yahoo-oauth#setup-oauth2")
    except Exception as e:
        print(f"⚠️  Yahoo API error (continuing without roster filter): {e}")

    results = pickups.rankFreeAgents(stats_df, last5_df, allPlayerData, rostered_nhle_ids)

    # ML score from the saved model (train with: python main.py train-pickups)
    # Models regress next-5-game FP/g; convert to 0-1 percentile ranks so the
    # heuristic blend and score displays keep a bounded scale. Low predicted
    # FP/g = cooling down, so the cooling score is inverted.
    current_players = latestGameState()
    current_players['pred_next5_fp'] = pickupModel.predict(current_players)
    current_players['ml_score'] = current_players['pred_next5_fp'].rank(pct=True)
    current_players['cooling_pred_next5_fp'] = coolingModel.predict(current_players)
    current_players['cooling_score'] = 1 - current_players['cooling_pred_next5_fp'].rank(pct=True)
    current_players = current_players.merge(
        allPlayerData[['id', 'full_name', 'positionCode']],
        left_on='playerId',
        right_on='id',
        how='left'
    )
    current_players['display_name'] = current_players['full_name'].fillna(current_players['name'])

    results['weighted_score_normalized'] = (results['weighted_score'] - results['weighted_score'].min()) / (results['weighted_score'].max() - results['weighted_score'].min())
    combined = results.merge(current_players[['playerId', 'ml_score', 'pred_next5_fp']],
                             left_on='player_id', right_on='playerId', how='left')
    combined = combined.dropna(subset=['ml_score'])
    combined['final_score'] = 0.3 * combined['weighted_score_normalized'] + 0.7 * combined['ml_score']

    print("\n=== Top available pickups (heuristic + ML blend) ===")
    print(combined[['full_name', 'positionCode', 'weighted_score', 'pred_next5_fp', 'ml_score', 'final_score']]
          .sort_values('final_score', ascending=False)
          .head(20)
          .to_string())

    print("\n=== Cooling down (drop candidates watch list) ===")
    print(current_players[['display_name', 'positionCode', 'cooling_pred_next5_fp', 'cooling_score', 'gamesPlayed']]
          .sort_values('cooling_score', ascending=False)
          .head(20)
          .to_string())


def loadPlayerSeasonFeatures():
    """Draft feature rows from the cached player-season table (built by
    scripts/build_player_seasons.py -- see fht-operations; not rebuilt here
    because that re-reads the 2.6 GB MoneyPuck history)."""
    seasons_path = os.path.join('data', 'processed', 'player_seasons.csv')
    if not os.path.exists(seasons_path):
        raise FileNotFoundError(
            f"{seasons_path} missing -- run scripts/build_player_seasons.py first")
    player_seasons = pd.read_csv(seasons_path)
    return draftFeatures.build_draft_features(player_seasons)


def trainDraft():
    """Train the draft ranker on historical player-season data (Phase B, see PROJECT-PLAN.md)."""
    draftModel.train(loadPlayerSeasonFeatures())


def buildCurrentDraftProjections():
    """Build every current-season skater projection used by draft and keeper tools."""
    df = loadPlayerSeasonFeatures()
    current = df[df['season'] == CURRENT_SEASON].copy()
    current['projected_fpPerGame'] = draftModel.predict(current)

    rankings = current[['playerId', 'full_name', 'position', 'gamesPlayed',
                        'fpPerGame', 'projected_fpPerGame']].copy()
    # age at the UPCOMING season start (draft-day age), one year past the
    # feature season's age_at_season_start
    rankings['age'] = current['age_at_season_start'] + 1
    rankings['projected_total'] = rankings['projected_fpPerGame'] * 78
    rankings['delta_vs_last'] = rankings['projected_fpPerGame'] - rankings['fpPerGame']

    # --- Explainability: data-driven confidence + top SHAP factors ---
    # Computed here, before the sort and keeper filter, so the columns ride
    # along with their rows. Display-only: nothing below feeds the model.
    # Seasons of prior history feeds confidence: distinct seasons each player
    # appears in, up to and including the feature season.
    seasons_of_history = (df[df['season'] <= CURRENT_SEASON]
                          .groupby('playerId')['season'].nunique())
    rankings['confidence'] = [
        draft_explain.compute_confidence(
            seasons_of_history=int(seasons_of_history.get(pid, 1)),
            feature_gp=int(gp),
            age=age,
            projection=float(proj),
            fp_w3=fp_w3,
        )
        for pid, gp, age, proj, fp_w3 in zip(
            current['playerId'], current['gamesPlayed'], rankings['age'],
            current['projected_fpPerGame'], current['fp_w3'])
    ]

    # Six factor columns: top 3 positive then top 3 negative SHAP contributions,
    # each a JSON {"label", "value"} cell (empty string when a slot is unused).
    contribs = draftModel.shap_contributions(current)
    factor_cols = [f'factor_{i}' for i in range(1, 7)]
    factor_rows = []
    for idx in current.index:
        factors = draft_explain.top_factors(contribs.loc[idx].to_dict(), top_n=3)
        cells = [json.dumps({'label': f['label'], 'value': round(f['value'], 4)})
                 for f in factors]
        cells += [''] * (len(factor_cols) - len(cells))
        factor_rows.append(cells[:len(factor_cols)])
    for col, values in zip(factor_cols, zip(*factor_rows)):
        rankings[col] = list(values)

    return rankings


def runDraft():
    """Rank this year's draft-eligible (non-keeper) players by projected fantasy value."""
    rankings = buildCurrentDraftProjections()
    # Display-side GP floor: an injury-shortened season can still carry keeper
    # value, but a 4-game 5-FP/g line is too noisy for the draft board.
    rankings = rankings[rankings['gamesPlayed'] >= 20].copy()

    # Draft pool must exclude anyone already kept -- keeper lists aren't in the Yahoo
    # API until draft day, so they're maintained manually in data/raw/keepers.csv.
    # Missing/empty file = keepers not announced yet: warn loudly and rank everyone
    # rather than refuse, so pre-draft-day rankings (and the frontend) still work.
    try:
        keeper_names = keepers.loadKeepers()
        before = len(rankings)
        rankings = keepers.filterOutKeepers(rankings, keeper_names)
        print(f"Keepers: removed {before - len(rankings)} of {len(keeper_names)} listed keepers from the pool")
    except (FileNotFoundError, ValueError) as e:
        print(f"⚠️  No keeper list applied ({e})")
        print("   Rankings include EVERY player. Fine before keepers are announced;")
        print("   on draft day, fill data/raw/keepers.csv and re-run.")

    rankings = rankings.sort_values('projected_fpPerGame', ascending=False)
    out_path = os.path.join('data', 'processed', 'draft_rankings.csv')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    rankings.to_csv(out_path, index=False)
    print(f"\nWrote {len(rankings)} players to {out_path}")

    print("\n=== Top 20 projected for next season (FP/game) ===")
    print(rankings[['full_name', 'position', 'age', 'gamesPlayed',
                    'fpPerGame', 'projected_fpPerGame', 'projected_total',
                    'delta_vs_last', 'confidence']]
          .head(20)
          .to_string(index=False))


def runKeeper():
    """Rank the authenticated Yahoo roster's best four skater keepers."""
    projections = buildCurrentDraftProjections()
    roster = yahooAPI.getMyRoster()
    rankings = keeper.analyze_keepers(roster, projections)
    rankings['target_season'] = keeper.target_season_label(CURRENT_SEASON)

    os.makedirs(os.path.dirname(KEEPER_RANKINGS_PATH), exist_ok=True)
    rankings.to_csv(KEEPER_RANKINGS_PATH, index=False)

    recommended = rankings[rankings['is_recommended']].sort_values('keeper_rank')
    print(f"\nWrote {len(rankings)} roster rows to {KEEPER_RANKINGS_PATH}")
    if recommended.empty:
        print("No skater keeper recommendations were matched to the projection board.")
        return

    print("\n=== Recommended keepers ===")
    print(recommended[[
        'keeper_rank', 'full_name', 'position', 'projected_fpPerGame',
        'projected_total', 'raw_keeper_value', 'assigned_round', 'pick_cost',
        'net_keeper_value'
    ]].to_string(index=False))


def main():
    parser = argparse.ArgumentParser(description="Fantasy hockey tools")
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('train-pickups', help='train pickup + cooling models on historical seasons')
    sub.add_parser('pickups', help='rank available free agents (uses saved models)')
    sub.add_parser('train-draft', help='train the draft ranker on historical player-seasons')
    sub.add_parser('draft', help='rank this year\'s non-keeper players for the draft')
    sub.add_parser('keeper', help='rank four skater keepers from the authenticated Yahoo roster')
    spot = sub.add_parser('spot-check', help='replay the pickup ranking at historical dates and grade it')
    spot.add_argument('--date', type=int, help='single as-of date as YYYYMMDD (default: several across the season)')
    spot.add_argument('--top', type=int, default=15, help='size of the ranked list to grade')

    args = parser.parse_args()
    if args.command == 'train-pickups':
        trainPickups()
    elif args.command == 'pickups':
        runPickups()
    elif args.command == 'train-draft':
        trainDraft()
    elif args.command == 'draft':
        runDraft()
    elif args.command == 'keeper':
        runKeeper()
    elif args.command == 'spot-check':
        backtest.runSpotChecks(dates=[args.date] if args.date else None, top_n=args.top)


if __name__ == "__main__":
    main()
