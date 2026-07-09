# Features specific to the draft analysis task.
# Draft predictions care about season-long value, so features here
# should reflect a player's sustained ceiling and floor over a full season.
#
# Examples of what belongs here:
#   - Age and career trajectory
#   - Historical season totals
#   - Team powerplay usage trends
#   - Contract year / motivation factors (if data available)

import os

import pandas as pd


def build_draft_features(player_seasons) -> pd.DataFrame:
    """
    Takes the base player DataFrame (with shared features already applied)
    and adds draft-specific features.
    Returns a new DataFrame with the added columns.
    """
    sorted_player_seasons = player_seasons.sort_values(['playerId','season'])
    sorted_player_seasons['career_games'] = sorted_player_seasons.groupby('playerId')['gamesPlayed'].cumsum()
    # Fantasy value generated on the powerplay / total fantasy value. Convert PP
    # goals and assists to fantasy points (goals x3, assists x2) plus the +1 PPP
    # bonus each earns -- same fantasy-unit treatment as hitblock_share below, so
    # a goal-heavy PP producer scores higher than an assist-heavy one at equal PPP.
    sorted_player_seasons['PP_share'] = (
        sorted_player_seasons['totalPPGoals'] * 3
        + sorted_player_seasons['totalPPAssists'] * 2
        + sorted_player_seasons['totalPPP'] * 1
    ) / sorted_player_seasons['totalFP']
    sorted_player_seasons['hitblock_share'] = (
        sorted_player_seasons['totalHits'] * 0.15 + sorted_player_seasons['totalShotsBlocked'] * 0.35
    ) / sorted_player_seasons['totalFP']
    g = sorted_player_seasons.groupby('playerId')
    # features = this row's own concluded season (no shift)
    #   fpPerGame, PP_share, hitblock_share, xGoalsSurplus, avgIcetime already correct as-is
    # backward-looking trajectory (this IS "take prior seasons into account"):
    sorted_player_seasons['fp_delta']  = g['fpPerGame'].diff()            # t minus t-1
    sorted_player_seasons['fp_w3'] = (                                     # 50/30/20 weighted
        0.5*sorted_player_seasons['fpPerGame']
    + 0.3*g['fpPerGame'].shift(1)
    + 0.2*g['fpPerGame'].shift(2)
    )
    # target only (training rows only)
    sorted_player_seasons['target_fpPerGame'] = g['fpPerGame'].shift(-1)

    # Age at season start. birthDate comes from the NHL API landing endpoint
    # (data/raw/player_birthdates.csv, built by scripts/build_birthdates.py) --
    # players_cache.csv is current-roster only and misses retired players
    # (~18% coverage on training seasons).
    birthdates_path = os.path.join(
        os.path.dirname(__file__), '..', '..', 'data', 'raw', 'player_birthdates.csv')
    if os.path.exists(birthdates_path):
        birthdates = (pd.read_csv(birthdates_path)[['playerId', 'birthDate']]
                        .drop_duplicates('playerId'))
        sorted_player_seasons = sorted_player_seasons.merge(
            birthdates, on='playerId', how='left')
        birth = pd.to_datetime(sorted_player_seasons['birthDate'], errors='coerce')
        # MoneyPuck season 2023 == the 2023-24 season, which starts ~Oct 1, 2023.
        season_start = pd.to_datetime(
            sorted_player_seasons['season'].astype(str) + '-10-01')
        sorted_player_seasons['age_at_season_start'] = (
            (season_start - birth).dt.days / 365.25)
    else:
        print("player_birthdates.csv not found -- run scripts/build_birthdates.py; "
              "age_at_season_start set to NaN")
        sorted_player_seasons['age_at_season_start'] = pd.NA

    # Position one-hot. Keep the raw 'position' column too (concat instead of
    # get_dummies(columns=...) which would drop it) -- B4 rankings display and
    # Phase C replacement-level-by-position both need the readable value.
    position_dummies = pd.get_dummies(sorted_player_seasons['position'], prefix='pos')
    sorted_player_seasons = pd.concat([sorted_player_seasons, position_dummies], axis=1)

    return sorted_player_seasons