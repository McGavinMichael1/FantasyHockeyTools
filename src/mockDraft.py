"""Mock-draft backtest: would the board have beaten the owner's real draft?

This is the end-to-end test of the draft tool. Everything else grades the model
against a statistical metric (Spearman vs. baselines); this grades the *product*
against the thing it exists to replace -- the owner drafting by hand.

Distinct from src/backtest.py, which replays in-season *pickup* rankings.

## How the replay works

Opponents draft exactly who they really drafted; only the owner's picks change.
That keeps the simulation deterministic and answers the question actually being
asked -- "what if only I had this tool?" -- rather than requiring an opponent
model that would itself need validating.

At each of the owner's slots the board takes the highest-VORP player still
available, subject to positional caps (drafting nine centers would be a fake
win). When the board has taken a player an opponent really drafted, that
opponent falls back to the best available by the same rule; those substitutions
are counted and reported, because a high count means the result depends heavily
on the fallback rule rather than on the board.

## Reading the result

`total_fp` is the verdict, agreed up front: the sum of each roster's ACTUAL
fantasy points in the drafted-for season. Per-pick comparison is diagnostic
colour -- it shows where the board helped, but it ignores roster construction.

## Leakage -- read before believing a number

The shipped draft model refits on feature-seasons <= DRAFT_TRAIN_MAX + val,
whose labels are the season after. So:

  * Mocking the Oct 2024 draft (season 2023 features -> 2024-25 outcomes) is
    CONTAMINATED: the model was trained on those very outcomes. Use it to debug
    the harness, never as evidence.
  * Mocking the Oct 2025 draft (season 2024 features -> 2025-26 outcomes) is
    clean: 2025-26 had not happened when the model's labels were cut.

`leakage_warning` in the report says which case a given run is.
"""

from __future__ import annotations

import json
import os

import pandas as pd
from rapidfuzz import process

from src import season

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLAYER_SEASONS_PATH = os.path.join(BASE_DIR, '..', 'data', 'processed', 'player_seasons.csv')
REPORT_PATH = os.path.join(BASE_DIR, '..', 'reports', 'mock_draft_{year}.json')

NAME_MATCH_CUTOFF = 85  # same threshold as keepers.filterOutKeepers

# How many of each position the board is willing to roster. Derived from
# keeper.ROSTER_SLOTS (2C/2L/2R/4D/2UTIL/2G/5BN) with UTIL and bench headroom
# spread across the skater positions: a pure best-available board would happily
# draft nine centers and post a fake win, since FP does not care about slots.
MAX_BY_POSITION = {'C': 4, 'L': 4, 'R': 4, 'D': 6, 'G': 2}


def leakage_warning(draft_year: int) -> str | None:
    """Whether the shipped model already saw the season this run grades on.

    The model's newest label is the season after its last validation season.
    A draft in year Y is graded on season Y, so a run is contaminated whenever
    Y is at or before that boundary.
    """
    newest_label_season = max(season.DRAFT_VAL_SEASONS) + 1
    if draft_year <= newest_label_season:
        return (
            f"CONTAMINATED: the shipped model trained on labels through season "
            f"{newest_label_season}, which includes the {draft_year} outcomes this "
            f"run grades on. Valid for checking the harness, NOT as evidence."
        )
    return None


def resolve_picks(draft_df: pd.DataFrame, board: pd.DataFrame,
                  cutoff: int = NAME_MATCH_CUTOFF) -> pd.DataFrame:
    """Attach each draft pick to a board row by fuzzy name match.

    Yahoo display names and MoneyPuck names disagree often enough (accents,
    Jr./Sr., nicknames) that exact matching drops real players. Unmatched picks
    keep their row with a null playerId rather than disappearing -- dropping
    them would shift every later pick's position in the replay.
    """
    candidates = board['full_name'].astype(str).tolist()
    by_name = board.drop_duplicates('full_name').set_index('full_name')

    matched_ids, matched_names = [], []
    claimed = set()
    for raw_name in draft_df['player_name']:
        if not isinstance(raw_name, str) or not raw_name.strip():
            matched_ids.append(None)
            matched_names.append(None)
            continue
        match = process.extractOne(raw_name, candidates, score_cutoff=cutoff)
        if not match:
            matched_ids.append(None)
            matched_names.append(None)
            continue
        board_name = match[0]
        if board_name in claimed:
            # Two Yahoo names collapsing onto one board row means one of them is
            # wrong; taking it twice would double-count a player's season.
            print(f"⚠️  '{raw_name}' matched '{board_name}', already claimed -- leaving unmatched")
            matched_ids.append(None)
            matched_names.append(None)
            continue
        claimed.add(board_name)
        matched_ids.append(by_name.loc[board_name, 'playerId'])
        matched_names.append(board_name)

    resolved = draft_df.copy()
    resolved['playerId'] = matched_ids
    resolved['board_name'] = matched_names
    return resolved


def _best_available(board: pd.DataFrame, taken: set, counts: dict) -> pd.Series | None:
    """Highest-VORP player left who does not blow a positional cap."""
    for _, row in board.iterrows():
        if row['playerId'] in taken:
            continue
        position = row['position']
        if counts.get(position, 0) >= MAX_BY_POSITION.get(position, 99):
            continue
        return row
    return None


def replay(resolved: pd.DataFrame, board: pd.DataFrame, my_team_key: str) -> dict:
    """Run the draft twice over: once as it happened, once with the board.

    Returns the owner's actual roster, the board's roster, and bookkeeping about
    how often the fallback rule had to fire.
    """
    ordered = resolved.sort_values('pick')
    ranked = board.sort_values('vorp', ascending=False)

    taken: set = set()
    my_actual, board_roster = [], []
    counts: dict = {}
    substitutions = []
    unmatched_opponent_picks = 0

    for _, pick in ordered.iterrows():
        is_mine = pick['team_key'] == my_team_key
        player_id = pick['playerId']

        if is_mine:
            choice = _best_available(ranked, taken, counts)
            if choice is None:
                print(f"⚠️  Board had nobody left at pick {pick['pick']}")
                continue
            taken.add(choice['playerId'])
            counts[choice['position']] = counts.get(choice['position'], 0) + 1
            board_roster.append({
                'pick': int(pick['pick']),
                'playerId': int(choice['playerId']),
                'name': choice['full_name'],
                'position': choice['position'],
                'vorp': float(choice['vorp']) if pd.notna(choice['vorp']) else None,
            })
            # The owner's real pick still comes off the board for everyone else.
            if pd.notna(player_id):
                my_actual.append({
                    'pick': int(pick['pick']),
                    'playerId': int(player_id),
                    'name': pick['board_name'],
                })
            else:
                my_actual.append({
                    'pick': int(pick['pick']),
                    'playerId': None,
                    'name': pick['player_name'],
                })
            continue

        # Opponent: take their real player unless the board already has them.
        if pd.isna(player_id):
            # Unresolved name -- nobody comes off the board, so this player stays
            # available to the board. Slightly favours the board, hence counted.
            unmatched_opponent_picks += 1
            continue
        if player_id not in taken:
            taken.add(player_id)
            continue
        # The board took this opponent's real player. They fall back to best
        # available. No positional cap is applied: we do not model opponent
        # rosters, and inventing constraints for them would be a guess that
        # changes the owner's result.
        replacement = _best_available(ranked, taken, {})
        if replacement is not None:
            taken.add(replacement['playerId'])
            substitutions.append({
                'pick': int(pick['pick']),
                'wanted': pick['board_name'],
                'got': replacement['full_name'],
            })

    return {
        'my_actual': my_actual,
        'board_roster': board_roster,
        'substitutions': substitutions,
        'unmatched_opponent_picks': unmatched_opponent_picks,
    }


def load_outcomes(outcome_season: int, path: str = PLAYER_SEASONS_PATH) -> pd.DataFrame:
    """Actual fantasy production for the season a draft was made for."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} missing -- run scripts/build_player_seasons.py first")
    seasons = pd.read_csv(path)
    outcomes = seasons[seasons['season'] == outcome_season]
    if outcomes.empty:
        raise ValueError(
            f"No player-season rows for season {outcome_season}; cannot grade a "
            f"draft made for it. Available: {sorted(seasons['season'].unique())}")
    # One row per player per season is the table's contract; a duplicate would
    # make .loc return a Series and silently inflate a roster's total.
    duplicates = outcomes['playerId'].duplicated().sum()
    if duplicates:
        raise ValueError(
            f"{duplicates} duplicate playerIds in season {outcome_season} of {path} -- "
            f"rebuild it with scripts/build_player_seasons.py")
    return outcomes.set_index('playerId')


def grade(roster: list, outcomes: pd.DataFrame) -> dict:
    """Sum a roster's ACTUAL fantasy points, counting misses honestly.

    A player with no row for the outcome season did not play -- injury, AHL,
    Europe. That scores zero rather than being skipped: a draft pick that
    produced nothing is a real cost of the pick, and dropping it would flatter
    whichever roster whiffed more.
    """
    total, lines, missing = 0.0, [], 0
    for entry in roster:
        player_id = entry.get('playerId')
        fp = 0.0
        if player_id is not None and player_id in outcomes.index:
            fp = float(outcomes.loc[player_id, 'totalFP'])
        else:
            missing += 1
        total += fp
        lines.append({**entry, 'actual_fp': round(fp, 1)})
    return {
        'total_fp': round(total, 1),
        'players': len(roster),
        'no_outcome_rows': missing,
        'picks': lines,
    }


def compare(replayed: dict, outcomes: pd.DataFrame) -> dict:
    """Grade both rosters and pair them pick-for-pick."""
    actual = grade(replayed['my_actual'], outcomes)
    board = grade(replayed['board_roster'], outcomes)

    head_to_head = []
    for mine, theirs in zip(actual['picks'], board['picks']):
        head_to_head.append({
            'pick': mine['pick'],
            'actual': mine['name'],
            'actual_fp': mine['actual_fp'],
            'board': theirs['name'],
            'board_fp': theirs['actual_fp'],
            'delta': round(theirs['actual_fp'] - mine['actual_fp'], 1),
        })

    return {
        'verdict': {
            'actual_total_fp': actual['total_fp'],
            'board_total_fp': board['total_fp'],
            'board_minus_actual': round(board['total_fp'] - actual['total_fp'], 1),
            'board_wins': board['total_fp'] > actual['total_fp'],
        },
        'actual_roster': actual,
        'board_roster': board,
        'head_to_head': head_to_head,
        'substitutions': replayed['substitutions'],
        'unmatched_opponent_picks': replayed['unmatched_opponent_picks'],
    }


def owner_team_key(draft_df: pd.DataFrame) -> str:
    """Which team key the cached draft results say is the owner's."""
    if 'is_mine' not in draft_df.columns:
        raise ValueError(
            "Cached draft results predate the is_mine column. Re-fetch with "
            "yahooAPI.loadDraftResults(year, refresh=True).")
    mine = draft_df[draft_df['is_mine'].astype(bool)]
    if mine.empty:
        raise ValueError("No picks flagged is_mine -- cannot tell which roster is the owner's.")
    keys = mine['team_key'].unique()
    if len(keys) > 1:
        raise ValueError(f"Picks flagged is_mine span several teams: {list(keys)}")
    return keys[0]


def write_report(result: dict, year: int, path: str = None) -> str:
    """Persist the result as text.

    Model metrics have so far survived only in stdout and overwritable PNGs, and
    a plot collision already destroyed the only record of one AUC. A mock draft
    is run at most once per season -- it does not get to be ephemeral.
    """
    path = path or REPORT_PATH.format(year=year)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(result, handle, indent=2)
    return path
