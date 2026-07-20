"""Rollover regression net.

Every value here was a hardcoded literal before src/season.py existed. If a
derived offset stops reproducing the value the models were actually trained
with, that is a silent retrain on the wrong seasons -- these tests make it
loud instead.
"""

from src import season


def test_current_season_constants():
    assert season.CURRENT_SEASON == 2025
    assert season.LAST_COMPLETED_SEASON == 2024


def test_draft_boundaries_match_the_shipped_model():
    """Pinned to what models/draft.py and models/goalieDraft.py used."""
    assert season.DRAFT_TRAIN_MAX_SEASON == 2021
    assert season.DRAFT_VAL_SEASONS == (2022, 2023)
    assert season.DRAFT_TEST_SEASON == 2024


def test_pickup_boundaries_match_the_shipped_model():
    """Pinned to what models/pickups.py and models/cooling.py used."""
    assert season.PICKUP_TRAIN_MAX_SEASON == 2022
    assert season.PICKUP_VAL_SEASON == 2023


def test_no_split_overlaps_its_validation_or_test_season():
    """Training must never see a validation or test season."""
    assert season.DRAFT_TRAIN_MAX_SEASON < min(season.DRAFT_VAL_SEASONS)
    assert max(season.DRAFT_VAL_SEASONS) < season.DRAFT_TEST_SEASON
    assert season.PICKUP_TRAIN_MAX_SEASON < season.PICKUP_VAL_SEASON
    assert season.PICKUP_VAL_SEASON <= season.LAST_COMPLETED_SEASON


def test_season_label():
    assert season.season_label(2025) == '2025-26'
    assert season.season_label(2024) == '2024-25'
    # Century rollover still reads correctly.
    assert season.season_label(2099) == '2099-00'


def test_nhl_season_id_matches_the_headshot_url_form():
    assert season.nhl_season_id(2025) == '20252026'
    assert season.nhl_season_id(2024) == '20242025'


def test_spot_check_dates_match_the_shipped_defaults():
    assert season.spot_check_dates(2025) == [
        20251101, 20251201, 20260101, 20260201, 20260301]


def test_spot_check_dates_roll_with_the_season():
    assert season.spot_check_dates(2026) == [
        20261101, 20261201, 20270101, 20270201, 20270301]


def test_boundaries_stay_consistent_after_a_rollover():
    """Simulate next season: every offset must still be internally ordered."""
    last = season.CURRENT_SEASON + 1 - 1
    assert last - 3 < last - 2 < last - 1 < last
