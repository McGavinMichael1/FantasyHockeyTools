import argparse

from src import dataProcessing
from src import fantasyPoints
from src import moneypuck
from src import yahooAPI
from src.features import mlFeatures
from src.features import pickups
from src.models import cooling as coolingModel
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
    df = mlFeatures.loadMoneyPuckData()
    df = mlFeatures.buildRollingFeatures(df)
    current_df = df[df['season'] == CURRENT_SEASON].copy()
    games_played = current_df.groupby('playerId').size().reset_index(name='gamesPlayed')
    current_players = current_df.groupby('playerId').last().reset_index()
    current_players = current_players.merge(games_played, on='playerId')
    return current_players[current_players['gamesPlayed'] >= 20]


def runPickups():
    moneypuck.checkCurrentFreshness()

    # Heuristic ranker on NHL API data
    allPlayerData = dataProcessing.getAllPlayersWithCache()
    allPlayerData = dataProcessing.flattenPlayerNames(allPlayerData)
    stats_df = dataProcessing.getAllStatsWithCache(allPlayerData['id'])
    stats_df['fantasyPoints'] = stats_df.apply(lambda row: fantasyPoints.calculateSkaterPoints(row), axis=1)
    last5_df = dataProcessing.getAllLast5WithCache(allPlayerData['id'])
    last5_df['fantasyPoints'] = last5_df.apply(lambda row: fantasyPoints.calculateSkaterPoints(row), axis=1)

    lg = yahooAPI.getLeague()
    rostered_names = yahooAPI.getRosteredIds(lg)
    rostered_nhle_ids = yahooAPI.getRosteredNHLIds(rostered_names, allPlayerData)

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


def main():
    parser = argparse.ArgumentParser(description="Fantasy hockey tools")
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('train-pickups', help='train pickup + cooling models on historical seasons')
    sub.add_parser('pickups', help='rank available free agents (uses saved models)')

    args = parser.parse_args()
    if args.command == 'train-pickups':
        trainPickups()
    elif args.command == 'pickups':
        runPickups()


if __name__ == "__main__":
    main()
