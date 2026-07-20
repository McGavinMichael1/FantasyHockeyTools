"""Keeper value calculations for skaters and goalies.

This module is deliberately independent of Yahoo, the draft model, and the
frontend. Callers provide a Yahoo roster and a projected skater board.
"""

from __future__ import annotations

import pandas as pd
from rapidfuzz import process

from src import season


TEAM_COUNT = 10
KEEPER_COUNT = 4
KEEPER_ROUNDS = (18, 17, 16, 15)
KEEPER_TENURE = "unknown"
ROSTER_SLOTS = {
    "C": 2,
    "L": 2,
    "R": 2,
    "D": 4,
    "UTIL": 2,
    "G": 2,
    "BN": 5,
    "IR+": 2,
}
REPLACEMENT_RANKS = {"C": 24, "L": 24, "R": 24, "D": 48, "G": 20}
ELIGIBLE_POSITIONS = frozenset(REPLACEMENT_RANKS)


def league_rules() -> dict:
    """League assumptions used by deterministic keeper math and its advisor."""
    return {
        "team_count": TEAM_COUNT,
        "keeper_count": KEEPER_COUNT,
        "keeper_rounds": list(KEEPER_ROUNDS),
        "keeper_tenure": KEEPER_TENURE,
        "roster_slots": dict(ROSTER_SLOTS),
        "replacement_ranks": dict(REPLACEMENT_RANKS),
    }


def target_season_label(feature_season: int) -> str:
    """Keepers are kept FOR the season after the one they were rated on."""
    return season.season_label(feature_season + 1)


def _position(value) -> str | None:
    if pd.isna(value):
        return None
    value = str(value).upper()
    return {"C": "C", "LW": "L", "L": "L", "RW": "R", "R": "R", "D": "D", "G": "G"}.get(value)


def replacement_levels(projections: pd.DataFrame) -> dict[str, float]:
    """Positional replacement totals. A position absent from the board is
    skipped with a warning (e.g. goalies in skaters-only degraded mode);
    a position present but shallower than its rank is a data bug -> raise."""
    levels = {}
    for position, rank in REPLACEMENT_RANKS.items():
        players = projections[projections["position"] == position].sort_values(
            "projected_total", ascending=False
        )
        if players.empty:
            print(f"⚠️  No projected {position} rows on the board; "
                  f"skipping the {position} replacement level")
            continue
        if len(players) < rank:
            raise ValueError(f"Need at least {rank} projected {position}s for keeper values")
        levels[position] = float(players.iloc[rank - 1]["projected_total"])
    return levels


def round_pick_costs(projections: pd.DataFrame) -> dict[int, float]:
    board = projections.sort_values("projected_total", ascending=False).reset_index(drop=True)
    costs = {}
    for round_number in KEEPER_ROUNDS:
        start = (round_number - 1) * TEAM_COUNT
        picks = board.iloc[start : start + TEAM_COUNT]
        if len(picks) < TEAM_COUNT:
            required = max(KEEPER_ROUNDS) * TEAM_COUNT
            raise ValueError(f"Need at least {required} projected players to price keeper rounds")
        costs[round_number] = float(picks["projected_total"].mean())
    return costs


def vorp_column(projections: pd.DataFrame) -> pd.Series:
    """Value over positional replacement for every row: projected_total minus
    the position's replacement level. NaN where no level exists (position
    missing from the board), so degraded skaters-only exports still work."""
    levels = replacement_levels(projections)
    return pd.to_numeric(projections["projected_total"], errors="coerce") - (
        projections["position"].map(levels)
    )


def analyze_keepers(roster: list[dict], projections: pd.DataFrame) -> pd.DataFrame:
    """Return every Yahoo roster row with keeper values and four recommendations."""
    board = projections.copy()
    board["position"] = board["position"].map(_position)
    board["projected_total"] = pd.to_numeric(board["projected_total"], errors="coerce")
    board = board[board["position"].isin(ELIGIBLE_POSITIONS)].dropna(
        subset=["projected_total"]
    )
    levels = replacement_levels(board)
    pick_costs = round_pick_costs(board)
    names = board["full_name"].astype(str).tolist()

    rows = []
    for yahoo_player in roster:
        row = {
            "yahoo_player_id": str(yahoo_player.get("player_id") or ""),
            "yahoo_name": str(yahoo_player.get("name") or ""),
            "eligible_positions": yahoo_player.get("eligible_positions") or [],
            "selected_position": yahoo_player.get("selected_position"),
            "yahoo_status": yahoo_player.get("status") or "",
            "match_status": "unmatched",
            "excluded_reason": None,
            "is_recommended": False,
            "keeper_rank": pd.NA,
            "assigned_round": pd.NA,
            "pick_cost": pd.NA,
            "replacement_level": pd.NA,
            "raw_keeper_value": pd.NA,
            "net_keeper_value": pd.NA,
        }
        match = process.extractOne(row["yahoo_name"], names, score_cutoff=85)
        if not match:
            row["excluded_reason"] = "No projection match"
            rows.append(row)
            continue

        _, score, index = match
        player = board.iloc[index].to_dict()
        position = player.get("position")
        if position not in ELIGIBLE_POSITIONS:
            row["excluded_reason"] = "No positional projection"
            rows.append(row)
            continue

        row.update(player)
        row["match_status"] = "matched"
        row["match_score"] = round(float(score), 1)
        row["replacement_level"] = levels[position]
        row["raw_keeper_value"] = float(player["projected_total"]) - levels[position]
        rows.append(row)

    rankings = pd.DataFrame(rows)
    if rankings.empty:
        return rankings

    for column in board.columns:
        if column not in rankings.columns:
            rankings[column] = pd.NA

    candidates = rankings[rankings["match_status"] == "matched"].sort_values(
        ["raw_keeper_value", "projected_total", "playerId"],
        ascending=[False, False, True],
    )
    for rank, (index, round_number) in enumerate(
        zip(candidates.head(KEEPER_COUNT).index, KEEPER_ROUNDS), start=1
    ):
        rankings.loc[index, "keeper_rank"] = rank
        rankings.loc[index, "is_recommended"] = True
        rankings.loc[index, "assigned_round"] = round_number
        rankings.loc[index, "pick_cost"] = pick_costs[round_number]
        rankings.loc[index, "net_keeper_value"] = (
            rankings.loc[index, "raw_keeper_value"] - pick_costs[round_number]
        )

    return rankings
