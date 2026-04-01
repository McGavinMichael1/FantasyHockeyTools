from src import fantasyPoints
from src import nhlAPI
from src import dataProcessing
from src import yahooAPI
import os
from src.features import pickups
def main():
    """Main entry point for the fantasy hockey application."""
    print("Welcome to Fantasy Hockey!")

    # Your code here
    print(os.getcwd())
    team = "TOR"
    torontoData = nhlAPI.getRosterData(team)
    # print(torontoData['forwards'])
    df = dataProcessing.makeTeamDataframe(torontoData)
    # print(df.head())
    print(df.columns)
    team_names = nhlAPI.getTeamNames()
    allPlayerData = dataProcessing.getAllPlayersWithCache()
    allPlayerData = dataProcessing.flattenPlayerNames(allPlayerData)
    print(allPlayerData.head())
    ross_colton = nhlAPI.getPlayerStats(8479525)
    stats = dataProcessing.extractCurrentStats(ross_colton, 8479525)
    print(stats)
    stats_df = dataProcessing.getAllStatsWithCache(allPlayerData['id'])
    stats_df['fantasyPoints'] = stats_df.apply(lambda row: fantasyPoints.calculateSkaterPoints(row), axis=1)
    print(stats_df.shape)
    print(stats_df.head())
    last5_df = dataProcessing.getAllLast5WithCache(allPlayerData['id'])
    last5_df['fantasyPoints'] = last5_df.apply(lambda row: fantasyPoints.calculateSkaterPoints(row), axis=1)

    lg = yahooAPI.getLeague()
    rostered = yahooAPI.getRosteredIds(lg)
    print(f"Total rostered players: {len(rostered)}")
    print(list(rostered)[:10])  # first 10 names

    rostered_names = yahooAPI.getRosteredIds(lg)
    rostered_nhle_ids = yahooAPI.getRosteredNHLIds(rostered_names, allPlayerData)

    results = pickups.rankFreeAgents(stats_df, last5_df, allPlayerData, rostered_nhle_ids)
    print(results[['player_id', 'full_name', 'positionCode', 'season_ppg', 'fantasyPoints_last5', 'weighted_score']].head(20).to_string())



if __name__ == "__main__":
    main()
