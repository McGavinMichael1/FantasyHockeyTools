"""The pickup blend and feature cache have exactly one definition.

main.py and api_export.py held byte-identical copies of latestGameState and the
0.3/0.7 blend, so the CLI and the frontend could silently disagree after a
change to either.
"""

import pandas as pd

import api_export
import main
from src.features import pickups


def test_both_entry_points_use_the_shared_feature_cache():
    assert not hasattr(main, 'latestGameState')
    assert not hasattr(api_export, 'latestGameState')
    assert callable(pickups.latestGameState)


def test_blend_weights_sum_to_one():
    """A blend that doesn't sum to 1 silently rescales the headline score."""
    assert pickups.HEURISTIC_WEIGHT + pickups.ML_WEIGHT == 1.0


def test_blend_matches_the_shipped_formula():
    """Pinned to 0.3 * heuristic + 0.7 * ml, the weights both callers used."""
    assert pickups.blendScores(1.0, 0.0) == 0.3
    assert pickups.blendScores(0.0, 1.0) == 0.7
    assert pickups.blendScores(0.5, 0.5) == 0.5


def test_blend_is_vectorised_over_series():
    """Both callers pass DataFrame columns, not scalars."""
    result = pickups.blendScores(pd.Series([1.0, 0.0]), pd.Series([0.0, 1.0]))

    pd.testing.assert_series_equal(result, pd.Series([0.3, 0.7]))


def test_latest_game_state_serves_a_fresh_cache(tmp_path):
    """A fresh cache must not trigger the 30-60s rebuild."""
    cache = tmp_path / 'features.csv'
    pd.DataFrame({'playerId': [1, 2], 'gamesPlayed': [40, 50]}).to_csv(
        cache, index=False)

    result = pickups.latestGameState(cache_file=str(cache))

    assert sorted(result['playerId'].tolist()) == [1, 2]
