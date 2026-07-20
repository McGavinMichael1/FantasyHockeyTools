"""Every season-derived constant, in one place.

Season rollover used to mean hand-editing `2025`, `2024` and `20252026`
literals across main.py, api_export.py, backtest.py, five model modules and
mlFeatures -- with nothing to catch a missed one. Now only CURRENT_SEASON
moves, and everything else is derived from it.

MoneyPuck convention throughout: season 2025 IS the 2025-26 season.

Train/validation boundaries are expressed as offsets from the last completed
season so they roll automatically. This parameterizes the season-based split;
it does not change it -- splits stay season-based, never random rows, because
random splits put the same player's adjacent seasons on both sides and the
model memorizes players (see fht-architecture-contract). tests/test_season.py
pins every derived value.
"""

CURRENT_SEASON = 2025
# The newest season with a full set of results. The current season has no
# future games to label, so nothing trains on it.
LAST_COMPLETED_SEASON = CURRENT_SEASON - 1

# --- Draft and goalie rankers -------------------------------------------
# These predict NEXT season's FP/game, so a usable row needs a completed
# season after it. The test season gets ONE manual look after a model passes
# the validation gate, then is never touched again.
DRAFT_TRAIN_MAX_SEASON = LAST_COMPLETED_SEASON - 3
DRAFT_VAL_SEASONS = (LAST_COMPLETED_SEASON - 2, LAST_COMPLETED_SEASON - 1)
DRAFT_TEST_SEASON = LAST_COMPLETED_SEASON

# --- Pickup and cooling models ------------------------------------------
# The label is a next-5-game window inside a season, so these need one less
# season of headroom than the draft models. backtest.py grades them on
# CURRENT_SEASON, which is the real held-out set.
PICKUP_TRAIN_MAX_SEASON = LAST_COMPLETED_SEASON - 2
PICKUP_VAL_SEASON = LAST_COMPLETED_SEASON - 1


def season_label(season: int) -> str:
    """2025 -> '2025-26'. The human-facing form."""
    return f"{season}-{str(season + 1)[-2:]}"


def nhl_season_id(season: int) -> str:
    """2025 -> '20252026'. The NHL API's form (headshot URLs, landing keys)."""
    return f"{season}{season + 1}"


def spot_check_dates(season: int = None) -> list[int]:
    """As-of dates for backtest spot checks: Nov 1 through Mar 1, YYYYMMDD.

    Spread across the season so a ranking is graded in early, middle and late
    conditions rather than one lucky week.
    """
    season = CURRENT_SEASON if season is None else season
    return [int(f"{season}1101"), int(f"{season}1201"),
            int(f"{season + 1}0101"), int(f"{season + 1}0201"),
            int(f"{season + 1}0301")]
