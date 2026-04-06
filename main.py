from src.features.lstmFeatures import SEQUENCE_FEATURES
from src.features import mlFeatures
from src import fantasyPoints
from src import dataProcessing
from src import yahooAPI
from src.features import pickups
from src.models import pickups as pickupModel
from src.models import cooling as coolingModel
from src.models import lstmPickups as lstmModel

def main():
    # Load player roster and flatten names
    allPlayerData = dataProcessing.getAllPlayersWithCache()
    allPlayerData = dataProcessing.flattenPlayerNames(allPlayerData)

    # Load stats and calculate fantasy points
    stats_df = dataProcessing.getAllStatsWithCache(allPlayerData['id'])
    stats_df['fantasyPoints'] = stats_df.apply(lambda row: fantasyPoints.calculateSkaterPoints(row), axis=1)

    last5_df = dataProcessing.getAllLast5WithCache(allPlayerData['id'])
    last5_df['fantasyPoints'] = last5_df.apply(lambda row: fantasyPoints.calculateSkaterPoints(row), axis=1)

    # Get rostered players from Yahoo
    lg = yahooAPI.getLeague()
    rostered_names = yahooAPI.getRosteredIds(lg)
    rostered_nhle_ids = yahooAPI.getRosteredNHLIds(rostered_names, allPlayerData)

    # Rank available free agents
    results = pickups.rankFreeAgents(stats_df, last5_df, allPlayerData, rostered_nhle_ids)
    print(results[['full_name', 'positionCode', 'season_ppg', 'fantasyPoints_last5', 'weighted_score']].head(20).to_string())
    
    ## model pipeline
    df = mlFeatures.loadMoneyPuckData()
    df = mlFeatures.buildRollingFeatures(df)

    # Split before labeling — current season has no future games to label
    historical_df = df[df['season'] <= 2024].copy()
    current_df = df[df['season'] == 2025].copy()

    historical_df = mlFeatures.buildLabel(historical_df)
    print(historical_df[SEQUENCE_FEATURES].isna().sum())
    # lstmModel.train()
    # lstm_scores = lstmModel.predict(current_df)
    pickupModel.train(historical_df)

    # Predict on current season using most recent game state per player
    games_played = current_df.groupby('playerId').size().reset_index(name='gamesPlayed')
    current_players = current_df.groupby('playerId').last().reset_index()
    current_players = current_players.merge(games_played, on='playerId')
    current_players = current_players[current_players['gamesPlayed'] >= 20]

    current_players['ml_score'] = pickupModel.predict(current_players)
    # current_players['lstm_score'] = current_players['playerId'].map(lstm_scores)

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
    print(combined[['full_name', 'positionCode', 'weighted_score', 'ml_score', 'final_score']]
        .sort_values('final_score', ascending=False)
        .head(20)
        .to_string())
    
    coolingModel.train(historical_df)
    current_players['cooling_score'] = coolingModel.predict(current_players)
    print(current_players[['display_name', 'positionCode', 'cooling_score', 'gamesPlayed']]
        .sort_values('cooling_score', ascending=False)
        .head(20)
        .to_string())



if __name__ == "__main__":
    main()
