"""Skater-only keeper value calculations.

This module is deliberately independent of Yahoo, the draft model, and the
frontend. Callers provide a Yahoo roster and a projected skater board.
"""

from __future__ import annotations

import pandas as pd
from rapidfuzz import process


KEEPER_COUNT = 4
KEEPER_ROUNDS = (18, 17, 16, 15)
REPLACEMENT_RANKS = {"C": 24, "L": 24, "R": 24, "D": 48}
SKATER_POSITIONS = frozenset(REPLACEMENT_RANKS)


def target_season_label(feature_season: int) -> str:
    start_year = feature_season + 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def _position(value) -> str | None:
    if pd.isna(value):
        return None
    value = str(value).upper()
    return {"C": "C", "LW": "L", "L": "L", "RW": "R", "R": "R", "D": "D"}.get(value)


def _goalie(yahoo_player: dict) -> bool:
    positions = yahoo_player.get("eligible_positions") or []
    if isinstance(positions, str):
        positions = [positions]
    return (
        "G" in {str(position).upper() for position in positions}
        or str(yahoo_player.get("selected_position") or "").upper() == "G"
        or str(yahoo_player.get("position_type") or "").upper() == "G"
    )


def replacement_levels(projections: pd.DataFrame) -> dict[str, float]:
    levels = {}
    for position, rank in REPLACEMENT_RANKS.items():
        players = projections[projections["position"] == position].sort_values(
            "projected_total", ascending=False
        )
        if len(players) < rank:
            raise ValueError(f"Need at least {rank} projected {position}s for keeper values")
        levels[position] = float(players.iloc[rank - 1]["projected_total"])
    return levels


def round_pick_costs(projections: pd.DataFrame) -> dict[int, float]:
    board = projections.sort_values("projected_total", ascending=False).reset_index(drop=True)
    costs = {}
    for round_number in KEEPER_ROUNDS:
        start = (round_number - 1) * 10
        picks = board.iloc[start : start + 10]
        if len(picks) < 10:
            raise ValueError("Need at least 180 projected skaters to price keeper rounds")
        costs[round_number] = float(picks["projected_total"].mean())
    return costs


def analyze_keepers(roster: list[dict], projections: pd.DataFrame) -> pd.DataFrame:
    """Return every Yahoo roster row with keeper values and four recommendations."""
    board = projections.copy()
    board["position"] = board["position"].map(_position)
    board["projected_total"] = pd.to_numeric(board["projected_total"], errors="coerce")
    board = board[board["position"].isin(SKATER_POSITIONS)].dropna(
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
        if _goalie(yahoo_player):
            row["match_status"] = "goalie"
            row["excluded_reason"] = "Goalies are excluded from keeper analysis"
            rows.append(row)
            continue

        match = process.extractOne(row["yahoo_name"], names, score_cutoff=85)
        if not match:
            row["excluded_reason"] = "No projection match"
            rows.append(row)
            continue

        _, score, index = match
        player = board.iloc[index].to_dict()
        position = player.get("position")
        if position not in SKATER_POSITIONS:
            row["excluded_reason"] = "Not a skater projection"
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
