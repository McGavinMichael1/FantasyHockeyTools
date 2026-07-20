import time
import pandas as pd
import numpy as np
from src import nhlAPI
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import ast

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DATA_DIR = os.path.join(BASE_DIR, '..', 'data', 'raw')

MAX_WORKERS = 5
# Rows are flushed to a .partial sidecar every this many completions, so an
# interrupted build (Ctrl-C, dead laptop, stalled network) loses at most this
# many players instead of all of them. The July 2026 incident lost ~2400.
CHECKPOINT_EVERY = 100

def makeTeamDataframe(jsonData):
    forwards = jsonData['forwards']
    defensemen = jsonData['defensemen']
    goalies = jsonData['goalies']
    roster_dict = forwards + defensemen + goalies
    df = pd.DataFrame(roster_dict)
    return df

def flattenPlayerNames(players_df):
    def extract_default(x):
        if isinstance(x, dict):
            return x['default']
        return ast.literal_eval(x)['default']
    players_df = players_df.copy()
    players_df['first'] = players_df['firstName'].apply(extract_default)
    players_df['last'] = players_df['lastName'].apply(extract_default)
    players_df['full_name'] = players_df['first'] + ' ' + players_df['last']
    return players_df

def makeAllPlayersDataFrame(teamNames):
    all_dfs = []
    for index, team in enumerate(teamNames, start=1):
        print(f"Fetching roster {index}/{len(teamNames)}: {team}")
        teamData = nhlAPI.getRosterData(team)
        all_dfs.append(makeTeamDataframe(teamData))
    return pd.concat(all_dfs, ignore_index=True)


def _partialPath(cache_file):
    return f"{cache_file}.partial"


def readPartial(cache_file):
    """Rows left behind by an interrupted fetch, or None.

    A build that dies mid-flight (the 12-hour hang, a closed laptop) writes its
    progress here; the next run folds these in and only fetches what is still
    missing, instead of starting from zero.
    """
    path = _partialPath(cache_file)
    if not os.path.exists(path):
        return None
    try:
        partial = pd.read_csv(path)
    except (pd.errors.EmptyDataError, OSError):
        return None
    if partial.empty:
        return None
    print(f"Resuming: {len(partial)} rows recovered from {os.path.basename(path)}")
    return partial


def clearPartial(cache_file):
    path = _partialPath(cache_file)
    if os.path.exists(path):
        os.remove(path)


def _reportProgress(done, total, started):
    elapsed = time.time() - started
    rate = done / elapsed if elapsed else 0
    remaining = (total - done) / rate if rate else 0
    print(f"  {done}/{total} players ({elapsed / 60:.1f}m elapsed, "
          f"~{remaining / 60:.1f}m left)")


def fetchAllPlayers(player_ids, extract_fn, cache_file=None):
    """Fetch every id through a small thread pool and return the rows.

    Uses as_completed rather than executor.map: map yields in *input* order, so
    a single slow or stalled worker blocks every later result even after it has
    arrived. With bounded timeouts in nhlAPI a stall now fails fast, but
    as_completed also means progress is visible and checkpointable.

    extract_fn may return a dict (one row) or a list of dicts (many rows).
    When cache_file is given, accumulated rows are flushed to its .partial
    sidecar every CHECKPOINT_EVERY completions.
    """
    player_ids = list(player_ids)
    total = len(player_ids)
    rows = []
    started = time.time()

    def worker(player_id):
        try:
            return extract_fn(nhlAPI.getPlayerStats(player_id), player_id)
        except Exception as e:
            print(f"Failed for player {player_id}: {e}")
            return None

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(worker, player_id) for player_id in player_ids]
        for done, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            if isinstance(result, list):
                rows.extend(result)
            elif result is not None:
                rows.append(result)
            if done % CHECKPOINT_EVERY == 0 or done == total:
                _reportProgress(done, total, started)
                if cache_file and rows:
                    pd.DataFrame(rows).to_csv(_partialPath(cache_file), index=False)

    return pd.DataFrame(rows)

def getWithCache(make_fn, player_ids, cache_file):
    if os.path.exists(cache_file):
        age_hours = (time.time() - os.path.getmtime(cache_file)) / 3600
        if age_hours < 24:
            return pd.read_csv(cache_file)
    df = make_fn(player_ids)
    df.to_csv(cache_file, index=False)
    return df

def getAllPlayersWithCache():
    make_fn = lambda _: makeAllPlayersDataFrame(nhlAPI.getTeamNames())
    return getWithCache(make_fn, None, os.path.join(RAW_DATA_DIR, 'players_cache.csv'))

def extractBirthDate(data, player_id):
    return {'playerId': player_id, 'birthDate': data.get('birthDate')}

def birthDatesCachePath():
    return os.path.join(RAW_DATA_DIR, 'player_birthdates.csv')


def makeAllBirthDatesDataFrame(player_ids):
    return fetchAllPlayers(player_ids, extractBirthDate,
                           cache_file=birthDatesCachePath())

def getAllBirthDatesWithCache(player_ids):
    # birthDates are immutable, so cache permanently -- unlike getWithCache's
    # 24h expiry, never refetch once the file exists. Covers retired players
    # that players_cache.csv (current roster only) can't.
    #
    # Prefer appendMissingBirthDates for anything that runs more than once:
    # this returns the cache as-is, so a player who appeared after the cache
    # was first written never gets a birthDate (and silently carries NaN age
    # into the draft model).
    cache_file = birthDatesCachePath()
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file)
    df = makeAllBirthDatesDataFrame(player_ids)
    df.to_csv(cache_file, index=False)
    clearPartial(cache_file)
    return df


def extractGoalieSeasons(data, player_id):
    """NHL regular-season goalie rows from a landing response.

    Filters to gameTypeId 2 (regular season) + leagueAbbrev NHL, converts the
    season key to MoneyPuck convention (20232024 -> 2023). Traded goalies get
    one row per team per season here -- aggregateGoalieSeasonRows sums them.
    """
    rows = []
    for s in data.get('seasonTotals', []):
        if s.get('gameTypeId') != 2 or s.get('leagueAbbrev') != 'NHL':
            continue
        rows.append({
            'playerId': player_id,
            'season': s['season'] // 10000,
            'gamesPlayed': s.get('gamesPlayed') or 0,
            'gamesStarted': s.get('gamesStarted') or 0,
            'wins': s.get('wins') or 0,
            'losses': s.get('losses') or 0,
            'otLosses': s.get('otLosses') or 0,
            'shutouts': s.get('shutouts') or 0,
            'goalsAgainst': s.get('goalsAgainst') or 0,
            'shotsAgainst': s.get('shotsAgainst') or 0,
        })
    return rows


def aggregateGoalieSeasonRows(rows):
    """One row per (playerId, season): sums the per-team stint rows."""
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.groupby(['playerId', 'season'], as_index=False).sum()


def goalieSeasonsCachePath():
    return os.path.join(RAW_DATA_DIR, 'goalie_nhl_seasons.csv')


def makeGoalieSeasonsDataFrame(player_ids):
    # extractGoalieSeasons returns a LIST of rows per player (one per season,
    # and one per team stint for traded goalies); fetchAllPlayers flattens it.
    rows = fetchAllPlayers(player_ids, extractGoalieSeasons,
                           cache_file=goalieSeasonsCachePath())
    return aggregateGoalieSeasonRows(rows)


def _resumeCached(cache_file, key):
    """Committed cache plus any rows recovered from an interrupted run.

    `key` is the identity of a row: one row per player for birthdates, but one
    row per player-season for goalie records -- deduping goalies on playerId
    alone would throw away every season but one.
    """
    frames = [frame for frame in (
        pd.read_csv(cache_file) if os.path.exists(cache_file) else None,
        readPartial(cache_file),
    ) if frame is not None and not frame.empty]
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True).drop_duplicates(key)


def getGoalieSeasonsWithCache(player_ids):
    """Permanent cache (like birthdates), plus append-missing: ids absent
    from the cache are fetched and appended. Completed seasons never change;
    at season rollover DELETE data/raw/goalie_nhl_seasons.csv so every
    goalie's newest season gets fetched fresh (a few minutes, threaded).
    """
    cache_file = goalieSeasonsCachePath()
    cached = _resumeCached(cache_file, ['playerId', 'season'])
    if cached is not None:
        missing = sorted(set(player_ids) - set(cached['playerId']))
        if not missing:
            cached.to_csv(cache_file, index=False)
            clearPartial(cache_file)
            return cached
        combined = pd.concat([cached, makeGoalieSeasonsDataFrame(missing)],
                             ignore_index=True)
        combined.to_csv(cache_file, index=False)
        clearPartial(cache_file)
        return combined
    df = makeGoalieSeasonsDataFrame(player_ids)
    df.to_csv(cache_file, index=False)
    clearPartial(cache_file)
    return df


def appendMissingBirthDates(player_ids):
    """getAllBirthDatesWithCache returns the cache as-is when it exists; this
    also fetches ids the cache lacks (goalies were never in player_seasons,
    so the draft-era birthdate build skipped them, and each season's rookies
    are missing until someone refetches them).

    This is the resumable entry point: an interrupted run's .partial rows are
    folded back in, so re-running picks up where it stopped rather than
    refetching thousands of players.
    """
    cache_file = birthDatesCachePath()
    cached = _resumeCached(cache_file, 'playerId')
    if cached is None:
        return getAllBirthDatesWithCache(player_ids)
    missing = sorted(set(player_ids) - set(cached['playerId']))
    if not missing:
        cached.to_csv(cache_file, index=False)
        clearPartial(cache_file)
        return cached
    print(f"Fetching birthDate for {len(missing)} players missing from the cache...")
    combined = pd.concat([cached, makeAllBirthDatesDataFrame(missing)],
                         ignore_index=True)
    combined.to_csv(cache_file, index=False)
    clearPartial(cache_file)
    return combined