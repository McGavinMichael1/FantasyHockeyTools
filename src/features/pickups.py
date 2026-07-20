# Features specific to the mid-season pickup task.
# Pickup predictions care about short-term value (next 2-4 weeks), so features
# here should capture recent form, upcoming schedule, and role changes.
#
# Examples of what belongs here:
#   - Rolling fantasy points (last 7, 14, 30 days)
#   - Ice time trend (increasing / decreasing)
#   - Upcoming opponent strength
#   - Games remaining in next 2 weeks
#   - Power play opportunity trend

import os
import time

import pandas as pd

from src import season
from src.features import mlFeatures

CURRENT_FEATURES_CACHE = os.path.join(
    'data', 'processed', 'current_players_features.csv')
CACHE_MAX_AGE_HOURS = 24
# A rate stat needs a sample behind it before it means anything.
MIN_GAMES_PLAYED = 20
# Blend of the heuristic ranking and the model's percentile. Lives here, with
# the heuristic it blends, so the CLI and the frontend export cannot drift
# apart -- they were separate copies of this number until July 2026.
HEURISTIC_WEIGHT = 0.3
ML_WEIGHT = 0.7


def latestGameState(cache_file=CURRENT_FEATURES_CACHE):
    """Most recent game-state row per current-season player with enough games.

    Rebuilding this walks the whole game-log history and recomputes rolling
    windows (30-60s), so it is cached for a day. Both `main.py pickups` and
    `api_export.py` call this -- they used to hold byte-identical copies, which
    meant any change to the cache policy or the GP floor silently applied to
    only one of them.
    """
    if os.path.exists(cache_file):
        age_hours = (time.time() - os.path.getmtime(cache_file)) / 3600
        if age_hours < CACHE_MAX_AGE_HOURS:
            print(f"Loading cached current player features ({age_hours:.1f}h old)")
            return pd.read_csv(cache_file)

    print("Computing current player features (this may take 30-60 seconds)...")
    df = mlFeatures.loadMoneyPuckData()
    df = mlFeatures.buildRollingFeatures(df)
    current_df = df[df['season'] == season.CURRENT_SEASON].copy()

    games_played = current_df.groupby('playerId').size().reset_index(name='gamesPlayed')
    current_players = current_df.groupby('playerId').last().reset_index()
    current_players = current_players.merge(games_played, on='playerId')
    current_players = current_players[
        current_players['gamesPlayed'] >= MIN_GAMES_PLAYED]

    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
    current_players.to_csv(cache_file, index=False)
    print(f"Cached features to {cache_file}")
    return current_players


def blendScores(heuristic_normalized, ml_score):
    """The single definition of the headline pickup score."""
    return HEURISTIC_WEIGHT * heuristic_normalized + ML_WEIGHT * ml_score


def build_pickup_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Takes the base player DataFrame (with shared features already applied)
    and adds pickup-specific features.
    Returns a new DataFrame with the added columns.
    """
    # TODO: implement pickup feature engineering
    raise NotImplementedError

def rankFreeAgents(pickup_stats_df, players_df, rostered_nhle_ids):
    """Heuristic free-agent ranking over MoneyPuck-derived pickup stats
    (moneypuck.buildPickupStats output). players_df is the NHL roster
    identity frame; players missing from it (e.g. recently moved) fall back
    to MoneyPuck's name/position instead of being dropped.
    """
    df = pd.merge(pickup_stats_df, players_df,
                  left_on='playerId', right_on='id', how='left')
    df['full_name'] = df['full_name'].fillna(df['name'])
    df['positionCode'] = df['positionCode'].fillna(df['position'])

    df['weighted_score'] = 0.6 * df['season_ppg'] + 0.4 * df['last5_fantasyPoints']

    df = df[df['positionCode'] != 'G']  # remove goalies
    df = df[~df['playerId'].isin(rostered_nhle_ids)]  # remove rostered players
    df = df[df['gamesPlayed'] >= 5]  # remove small sample size players

    return df.sort_values('weighted_score', ascending=False)

