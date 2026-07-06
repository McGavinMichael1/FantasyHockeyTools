# League-wide keeper input for the draft ranker.
#
# Yahoo doesn't expose which players are being kept until draft day itself, and
# keeper lists change every year, so this reads a manually maintained CSV instead
# of hitting an API. Before running the draft ranker each year, fill in
# data/raw/keepers.csv with one kept player's Yahoo display name per row under a
# `player_name` column.
#
# This is distinct from the future keeper *analyzer* (Phase C in PROJECT-PLAN.md,
# which decides which of MY players are worth keeping). This module only answers
# "who is out of this year's draft pool because someone already kept them."

import os

import pandas as pd
from rapidfuzz import process

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KEEPERS_PATH = os.path.join(BASE_DIR, '..', 'data', 'raw', 'keepers.csv')


def loadKeepers(path: str = KEEPERS_PATH) -> list[str]:
    """
    Read the manually maintained keepers file and return the kept player names
    (Yahoo display names, one per row under a `player_name` column).
    """
    # index_col=False: a stray trailing comma on one row (an easy mistake in a
    # hand-edited file) otherwise makes pandas mis-parse names into the index
    # instead of the player_name column.
    df = pd.read_csv(path, index_col=False)
    if 'player_name' not in df.columns:
        raise ValueError(f"{path} is missing a 'player_name' column")
    names = df['player_name'].dropna().str.strip()
    names = names[names != '']
    if names.empty:
        raise ValueError(f"{path} has no keeper names -- an empty keeper list silently drafts everyone")
    return names.tolist()


def filterOutKeepers(players_df: pd.DataFrame, keeper_names: list[str]) -> pd.DataFrame:
    """
    Given a draft-pool DataFrame (must have a `full_name` column) and a list of
    kept player names, return the subset of players_df that is still draft-eligible.

    Names won't match exactly -- see `yahooAPI.getRosteredNHLIds` for the existing
    fuzzy-matching approach (rapidfuzz `process.extractOne`) to resolve a free-text
    name to a row in a players DataFrame.
    """
    candidate_names = players_df['full_name'].tolist()

    matched_names = set()
    for keeper_name in keeper_names:
        match = process.extractOne(keeper_name, candidate_names, score_cutoff=85)
        if match:
            matched_names.add(match[0])
        else:
            print(f"No good match found for keeper {keeper_name}")

    return players_df[~players_df['full_name'].isin(matched_names)]
