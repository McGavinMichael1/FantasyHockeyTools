import pandas as pd

from src.features.mlFeatures import buildLabel


def test_build_label_keeps_continuous_next_5_avg():
    # 7 games, ascending scores. next_5_avg at game i is the mean of games
    # i+1..i+5 (strictly future, 5-game window, min 5 games):
    #   game 0: (2+3+4+5+6)/5 = 4.0
    #   game 1: (3+4+5+6+7)/5 = 5.0
    #   games 2-6: fewer than 5 future games -> row dropped
    df = pd.DataFrame({
        'playerId': [1] * 7,
        'season': [2023] * 7,
        'game_fantasy_points': [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
        'season_avg_so_far': [1.0] * 7,
    })

    out = buildLabel(df)

    assert list(out['next_5_avg']) == [4.0, 5.0]


def test_build_label_never_includes_current_game_in_target():
    # A huge score in the current game must not leak into its own label:
    # game 0's label averages games 1-5 (all zeros), not game 0 itself.
    df = pd.DataFrame({
        'playerId': [1] * 6,
        'season': [2023] * 6,
        'game_fantasy_points': [100.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        'season_avg_so_far': [1.0] * 6,
    })

    out = buildLabel(df)

    assert list(out['next_5_avg']) == [0.0]
