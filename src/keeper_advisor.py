"""Decision-ready, server-only context for the keeper roster advisor."""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

import pandas as pd

from src import keeper
from src.fantasyPoints import GOALIE_WEIGHTS, SKATER_WEIGHTS


SCHEMA_VERSION = 1
HISTORY_LIMIT = 3
CONTEXT_PATH = Path("data") / "processed" / "keeper_advisor_context.json"
FACTOR_COLS = tuple(f"factor_{number}" for number in range(1, 7))
STABLE_YAHOO_KEYS = (
    "league_key", "name", "num_teams", "scoring_type", "roster_positions",
)
SKATER_HISTORY_FIELDS = (
    "season", "gamesPlayed", "fpPerGame", "totalGoals",
    "totalPrimaryAssists", "totalSecondaryAssists", "totalShotsOnGoal",
    "totalHits", "totalShotsBlocked", "totalPPP", "avgIcetime",
    "xGoalsSurplus",
)
GOALIE_HISTORY_FIELDS = (
    "season", "gamesPlayed", "gamesStarted", "fpPerGame", "wins", "losses",
    "shutouts", "saves", "goalsAgainst", "save_pct", "gsax",
)
DECISION_COLUMNS = (
    "raw_keeper_value", "net_keeper_value", "pick_cost", "replacement_level",
    "projected_total", "projected_fpPerGame",
)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_clean(item) for item in value]
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _number(row: pd.Series, column: str, *, integer: bool = False):
    value = row.get(column)
    if value is None or pd.isna(value):
        return None
    return int(value) if integer else float(value)


def _factors(row: pd.Series) -> list[dict]:
    factors = []
    for column in FACTOR_COLS:
        value = row.get(column)
        if not isinstance(value, str) or not value:
            continue
        try:
            parsed = json.loads(value)
            factors.append({
                "label": str(parsed["label"]),
                "value": float(parsed["value"]),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return factors


def _history(history: pd.DataFrame | None, player_id: int | None,
             fields: tuple[str, ...]) -> list[dict]:
    if history is None or history.empty or player_id is None or "playerId" not in history:
        return []
    ids = pd.to_numeric(history["playerId"], errors="coerce")
    rows = history[ids == player_id].sort_values("season").tail(HISTORY_LIMIT)
    return [
        {field: _clean(row.get(field)) for field in fields if field in rows.columns}
        for _, row in rows.iterrows()
    ]


def _ensure_finite_decision_data(rankings: pd.DataFrame) -> None:
    """NaN means a value is absent (e.g. unmatched player); inf means the math broke."""
    scope = rankings
    if "match_status" in rankings.columns:
        scope = rankings[rankings["match_status"] == "matched"]
    for column in DECISION_COLUMNS:
        if column not in scope.columns:
            continue
        values = pd.to_numeric(scope[column], errors="coerce")
        offenders = scope.loc[values.abs() == float("inf")]
        if offenders.empty:
            continue
        names = ", ".join(str(name) for name in offenders.get("yahoo_name", offenders.index))
        raise ValueError(
            f"Keeper rankings contain non-finite decision data ({column}: {names})"
        )


def _board_comparisons(projections: pd.DataFrame) -> dict[int, dict]:
    board = projections.copy()
    board["playerId"] = pd.to_numeric(board["playerId"], errors="coerce")
    board["projected_total"] = pd.to_numeric(board["projected_total"], errors="coerce")
    board = board.dropna(subset=["playerId", "projected_total", "position"])
    levels = keeper.replacement_levels(board)
    board["vorp"] = board["projected_total"] - board["position"].map(levels)
    board["position_rank"] = (
        board.groupby("position")["projected_total"]
        .rank(ascending=False, method="min")
    )
    board["vorp_rank"] = board["vorp"].rank(ascending=False, method="min")
    return {
        int(row["playerId"]): {
            "position_rank": int(row["position_rank"]),
            "vorp_rank": int(row["vorp_rank"]) if pd.notna(row["vorp_rank"]) else None,
            "vorp": float(row["vorp"]) if pd.notna(row["vorp"]) else None,
        }
        for _, row in board.iterrows()
    }


def _roster_records(rankings: pd.DataFrame, projections: pd.DataFrame,
                    skater_history: pd.DataFrame | None,
                    goalie_history: pd.DataFrame | None) -> list[dict]:
    comparisons = _board_comparisons(projections)
    records = []
    for _, row in rankings.iterrows():
        player_id = _number(row, "playerId", integer=True)
        position = _clean(row.get("position"))
        record = {
            "player_id": player_id,
            "yahoo_player_id": str(row.get("yahoo_player_id") or ""),
            "yahoo_name": str(row.get("yahoo_name") or ""),
            "full_name": _clean(row.get("full_name")),
            "position": position,
            "eligible_positions": _clean(row.get("eligible_positions")) or [],
            "selected_position": _clean(row.get("selected_position")),
            "yahoo_status": str(row.get("yahoo_status") or ""),
            "match_status": str(row.get("match_status") or "unmatched"),
            "excluded_reason": _clean(row.get("excluded_reason")),
            "is_recommended": (
                bool(row.get("is_recommended"))
                if pd.notna(row.get("is_recommended")) else False
            ),
            "keeper_rank": _number(row, "keeper_rank", integer=True),
            "assigned_round": _number(row, "assigned_round", integer=True),
            "pick_cost": _number(row, "pick_cost"),
            "replacement_level": _number(row, "replacement_level"),
            "raw_keeper_value": _number(row, "raw_keeper_value"),
            "net_keeper_value": _number(row, "net_keeper_value"),
            "games_played": _number(row, "gamesPlayed", integer=True),
            "last_fp_per_game": _number(row, "fpPerGame"),
            "projected_fp_per_game": _number(row, "projected_fpPerGame"),
            "projected_games": _number(row, "projected_gp"),
            "projected_total": _number(row, "projected_total"),
            "delta_vs_last": _number(row, "delta_vs_last"),
            "age": _number(row, "age"),
            "confidence": _number(row, "confidence", integer=True),
            "factors": _factors(row),
            "history": _history(
                goalie_history if position == "G" else skater_history,
                player_id,
                GOALIE_HISTORY_FIELDS if position == "G" else SKATER_HISTORY_FIELDS,
            ),
            **comparisons.get(player_id, {
                "position_rank": None, "vorp_rank": None, "vorp": None,
            }),
        }
        records.append(_clean(record))
    return records


def _scenario_sets(records: list[dict], pick_costs: dict[int, float]) -> list[dict]:
    candidates = [
        record for record in records
        if record["match_status"] == "matched"
        and record["player_id"] is not None
        and record["raw_keeper_value"] is not None
    ]
    scenarios = []
    for combo in combinations(candidates, keeper.KEEPER_COUNT):
        ordered = sorted(
            combo,
            key=lambda player: (
                -player["raw_keeper_value"],
                -(player["projected_total"] or 0),
                player["player_id"],
            ),
        )
        players = []
        for player, round_number in zip(ordered, keeper.KEEPER_ROUNDS):
            pick_cost = float(pick_costs[round_number])
            players.append({
                "player_id": player["player_id"],
                "assigned_round": round_number,
                "pick_cost": pick_cost,
                "raw_keeper_value": float(player["raw_keeper_value"]),
                "net_keeper_value": float(player["raw_keeper_value"]) - pick_cost,
            })
        scenarios.append({
            "player_ids": sorted(player["player_id"] for player in ordered),
            "players": players,
            "total_model_value": sum(player["raw_keeper_value"] for player in players),
            "total_net_keeper_value": sum(player["net_keeper_value"] for player in players),
        })
    return sorted(scenarios, key=lambda scenario: scenario["player_ids"])


def _stable_yahoo(settings: dict | None) -> dict:
    settings = settings or {}
    return {
        key: _clean(settings[key])
        for key in STABLE_YAHOO_KEYS
        if key in settings
    }


def context_id_for(context_or_payload: dict) -> str:
    payload = {
        key: value for key, value in context_or_payload.items()
        if key not in {"context_id", "generated_at"}
    }
    encoded = json.dumps(
        _clean(payload), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_context(rankings: pd.DataFrame, projections: pd.DataFrame,
                  skater_history: pd.DataFrame | None = None,
                  goalie_history: pd.DataFrame | None = None,
                  yahoo_settings: dict | None = None,
                  generated_at: datetime | None = None) -> dict:
    if rankings.empty:
        raise ValueError("Cannot build keeper advisor context from an empty roster")
    _ensure_finite_decision_data(rankings)
    records = _roster_records(rankings, projections, skater_history, goalie_history)
    official = (
        rankings[rankings["is_recommended"].astype(bool)]
        .sort_values("keeper_rank")
    )
    official_ids = [int(player_id) for player_id in official["playerId"].dropna()]
    if len(official_ids) != keeper.KEEPER_COUNT:
        raise ValueError(f"Expected {keeper.KEEPER_COUNT} official keepers, got {len(official_ids)}")
    seasons = rankings.get("target_season", pd.Series(dtype=str)).dropna().astype(str).unique()
    if len(seasons) != 1:
        raise ValueError("Keeper roster must contain exactly one target season")
    rules = keeper.league_rules()
    yahoo_snapshot = _stable_yahoo(yahoo_settings)
    warnings = []
    yahoo_teams = yahoo_snapshot.get("num_teams")
    if yahoo_teams is not None and int(yahoo_teams) != rules["team_count"]:
        warnings.append(
            f"Yahoo reports {yahoo_teams} teams but keeper math uses {rules['team_count']}"
        )
    if rules["keeper_tenure"] == "unknown":
        warnings.append("Maximum keeper tenure is unknown")
    pick_costs = keeper.round_pick_costs(projections)
    if any(not math.isfinite(cost) for cost in pick_costs.values()):
        raise ValueError(
            "Projection board produced non-finite decision data in keeper pick costs"
        )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "season": seasons[0],
        "league": {
            **rules,
            "scoring_weights": {
                "skaters": dict(SKATER_WEIGHTS),
                "goalies": dict(GOALIE_WEIGHTS),
            },
            "yahoo_snapshot": yahoo_snapshot,
            "warnings": warnings,
        },
        "official_top_four": official_ids,
        "roster": records,
        "scenario_data": {
            "sets": _scenario_sets(records, pick_costs),
        },
    }
    timestamp = generated_at or datetime.now(timezone.utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "context_id": context_id_for(payload),
        "generated_at": timestamp.astimezone(timezone.utc).isoformat(),
        **{key: value for key, value in payload.items() if key != "schema_version"},
    }


def write_context(context: dict, path: str | os.PathLike = CONTEXT_PATH) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(context, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    os.replace(temporary, target)
