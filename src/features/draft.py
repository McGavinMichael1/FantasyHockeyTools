# Features specific to the draft analysis task.
# Draft predictions care about season-long value, so features here
# should reflect a player's sustained ceiling and floor over a full season.
#
# Examples of what belongs here:
#   - Age and career trajectory
#   - Historical season totals
#   - Team powerplay usage trends
#   - Contract year / motivation factors (if data available)

import pandas as pd
from src import keepers, moneypuck


def build_draft_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Takes the base player DataFrame (with shared features already applied)
    and adds draft-specific features.
    Returns a new DataFrame with the added columns.
    """
    player_seasons = moneypuck.buildPlayerSeasons(df)
    player_seasons = pd.get_dummies(player_seasons, columns=['position'], prefix='pos')
    sorted_player_seasons = player_seasons.sort_values(['playerId','season'])
    sorted_player_seasons['career_games'] = sorted_player_seasons.groupby('playerId')['gamesPlayed'].cumsum()
    sorted_player_seasons['PP_share'] = sorted_player_seasons['totalPPP'] / sorted_player_seasons['totalFP']
    sorted_player_seasons['hitblock_share'] = (
        sorted_player_seasons['totalHits'] * 0.15 + sorted_player_seasons['totalShotsBlocked'] * 0.35
    ) / sorted_player_seasons['totalFP']
    
    return sorted_player_seasons