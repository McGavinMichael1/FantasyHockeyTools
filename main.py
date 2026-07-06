import argparse

from src import backtest
from src import dataProcessing
from src import fantasyPoints
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


def loadLabeledHistory():
    """Rolling features + heating/cooling labels on completed seasons."""
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
    current_players = latestGameState()
    current_players['ml_score'] = pickupModel.predict(current_players)
    current_players['cooling_score'] = coolingModel.predict(current_players)
    current_players = current_players.merge(
        allPlayerData[['id', 'full_name', 'positionCode']],
        left_on='playerId',
        right_on='id',
        how='left'
    )
    current_players['display_name'] = current_players['full_name'].fillna(current_players['name'])

    results['weighted_score_normalized'] = (results['weighted_score'] - results['weighted_score'].min()) / (results['weighted_score'].max() - results['weighted_score'].min())
    combined = results.merge(current_players[['playerId', 'ml_score']],
                             left_on='player_id', right_on='playerId', how='left')
    combined = combined.dropna(subset=['ml_score'])
    combined['final_score'] = 0.3 * combined['weighted_score_normalized'] + 0.7 * combined['ml_score']

    print("\n=== Top available pickups (heuristic + ML blend) ===")
    print(combined[['full_name', 'positionCode', 'weighted_score', 'ml_score', 'final_score']]
          .sort_values('final_score', ascending=False)
          .head(20)
          .to_string())

    print("\n=== Cooling down (drop candidates watch list) ===")
    print(current_players[['display_name', 'positionCode', 'cooling_score', 'gamesPlayed']]
          .sort_values('cooling_score', ascending=False)
          .head(20)
          .to_string())


def trainDraft():
    """Train the draft ranker on historical player-season data (Phase B, see PROJECT-PLAN.md)."""
    # TODO: build the player-season aggregation table (src/moneypuck.py::buildPlayerSeasons)
    # TODO: build draft features (draftFeatures.build_draft_features)
    # TODO: call draftModel.train(df)
    raise NotImplementedError


def runDraft():
    """Rank this year's draft-eligible (non-keeper) players by projected fantasy value."""
    # TODO: load this season's player-season features (mirror latestGameState() above,
    #       but season-level per PROJECT-PLAN.md B1/B4 instead of rolling game-state)

    # Draft pool must exclude anyone already kept -- keeper lists aren't in the Yahoo
    # API until draft day, so they're maintained manually in data/raw/keepers.csv.
    keeper_names = keepers.loadKeepers()
    # TODO: current_players = keepers.filterOutKeepers(current_players, keeper_names)

    # TODO: build draft features (draftFeatures.build_draft_features)
    # TODO: predict with draftModel.predict(df)
    # TODO: join name/position/age, sort by projected value
    # TODO: save results to data/processed/draft_rankings.csv
    raise NotImplementedError


def main():
    parser = argparse.ArgumentParser(description="Fantasy hockey tools")
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('train-pickups', help='train pickup + cooling models on historical seasons')
    sub.add_parser('pickups', help='rank available free agents (uses saved models)')
    sub.add_parser('train-draft', help='train the draft ranker on historical player-seasons')
    sub.add_parser('draft', help='rank this year\'s non-keeper players for the draft')
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
    elif args.command == 'spot-check':
        backtest.runSpotChecks(dates=[args.date] if args.date else None, top_n=args.top)


if __name__ == "__main__":
    main()
