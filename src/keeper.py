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

# The league rule (owner, 2026-07-20) is "keeping a player costs your final 4
# picks -- whichever picks those happen to be." Rounds 18/17/16/15 are only what
# that resolves to in a draft where nobody traded picks, so this is a DEFAULT,
# not the rule.
#
# It understates the cost whenever late picks have been traded away. In 2025 the
# owner held only rounds 1-9, so his last four picks were overall 70/71/78/90 --
# priced against the current board that is 898.3 projected FP of real cost
# versus the 722.4 this constant assumes, a 24% understatement that inflates
# net_keeper_value by ~44 FP per keeper.
#
# Fixing it properly means pricing against the picks actually held; see
# .claude/skills/OPEN-QUESTIONS.md #1b. Keeper math is a class (a) change
# (fht-quality-gates) -- highest bar, tests first.
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
# Base replacement ranks: roughly TEAM_COUNT x starting slots, plus UTIL/bench
# headroom. This is the NO-KEEPER baseline -- see replacement_ranks() for the
# adjustment an actual keeper league needs.
REPLACEMENT_RANKS = {"C": 24, "L": 24, "R": 24, "D": 48, "G": 20}
ELIGIBLE_POSITIONS = frozenset(REPLACEMENT_RANKS)

# The minimum a legally fieldable roster needs at each position, from
# ROSTER_SLOTS (UTIL/BN/IR+ are flexible and impose no floor). Shared with
# mockDraft so the drafting rule and the keeper math cannot drift apart.
STARTING_SLOTS = {
    position: count for position, count in ROSTER_SLOTS.items()
    if position in ELIGIBLE_POSITIONS
}


def replacement_ranks(kept_counts: dict[str, int] | None = None) -> dict[str, int]:
    """Replacement ranks adjusted for players already kept at each position.

    Replacement level is the marginal *drafted* starter: what you end up with at
    a position if you spend your picks elsewhere. In a keeper league the league
    does not have to draft the slots its keepers already fill, so every keeper at
    a position pulls that position's rank down with it.

    Measured on the 2026 board (15 of 40 keepers are centers): the base rank of
    24 applied to the post-keeper pool sets C replacement ~26 FP below what
    league demand justifies, because it removes the keepers from the pool AND
    keeps counting their roster slots as still needing to be drafted.

    `None` or `{}` returns the base constant unchanged -- the degraded path when
    keepers have not been announced yet.
    """
    if not kept_counts:
        return dict(REPLACEMENT_RANKS)
    return {
        position: max(1, rank - int(kept_counts.get(position, 0)))
        for position, rank in REPLACEMENT_RANKS.items()
    }


def keeper_position_counts(keeper_names: list[str],
                           board: pd.DataFrame) -> dict[str, int]:
    """How many kept players sit at each position, resolved against a board.

    Keeper lists are hand-maintained Yahoo display names, so this fuzzy-matches
    at the same cutoff as keepers.filterOutKeepers -- the two must agree about
    who was removed, or the counts would not describe the filtered pool.
    """
    named = board.assign(full_name=board["full_name"].astype(str))
    candidates = named["full_name"].tolist()
    # drop_duplicates so a repeated name yields a scalar position, not a Series.
    positions = named.drop_duplicates("full_name").set_index("full_name")["position"]

    counts: dict[str, int] = {}
    for name in keeper_names:
        match = process.extractOne(name, candidates, score_cutoff=85)
        if not match:
            print(f"No good match found for keeper {name}")
            continue
        position = _position(positions.loc[match[0]])
        if position is None:
            continue
        counts[position] = counts.get(position, 0) + 1
    return counts


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


def replacement_levels(projections: pd.DataFrame,
                       kept_counts: dict[str, int] | None = None) -> dict[str, float]:
    """Positional replacement totals. A position absent from the board is
    skipped with a warning (e.g. goalies in skaters-only degraded mode);
    a position present but shallower than its rank is a data bug -> raise."""
    levels = {}
    for position, rank in replacement_ranks(kept_counts).items():
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


def round_pick_costs(projections: pd.DataFrame,
                     pool: pd.DataFrame | None = None,
                     kept_counts: dict[str, int] | None = None) -> dict[int, float]:
    """What a keeper round's pick is worth, in VALUE OVER REPLACEMENT.

    `pool` defaults to `projections`. A keeper costs picks you would otherwise
    spend on the pool, so pricing against a frame that still contains other
    teams' keepers overstates what those picks could actually have fetched.

    Three things this function has to get right, all of them once wrong:

    1. **Units.** The caller subtracts this from `raw_keeper_value`, which is
       value over positional replacement. This used to return the mean absolute
       `projected_total` of the round, so the subtraction mixed a surplus with a
       season total: on the 2026 board, 60-85 FP of keeper value minus 161-173 FP
       of "cost" made every keeper score deeply negative and the tool concluded
       "keep nobody." That was a unit error, not a finding.

    2. **Which players are in the round.** VORP is the board's default
       cross-position order (owner, 2026-07-16), so the ten players who actually
       go in round N are the ones ranked there BY VORP. Slicing by
       `projected_total` prices a round off players who would not have been
       picked in it.

       This also settles the "what position is an unknown future pick" question
       without having to guess or weight: each of the ten players in the slice
       has a position, so each has a replacement level, and the mean of their
       VORPs is the estimate. No position mix is assumed.

    3. **Floor at zero.** Forfeiting a pick can never be a gain. A
       below-replacement draftee is a bench player, interchangeable with a free
       waiver add -- that is what replacement level means -- so he contributes 0
       to a starting lineup, not a negative. Without the clip, keeping a player
       would score better the more worthless the pick it cost.

    Consequence worth reading before trusting the output: on the 2026 board the
    per-round value falls monotonically from +80.2 (round 1) through zero at
    round 10 to -25.0 (round 18), so KEEPER_ROUNDS 15-18 all price at 0 and
    keeping is free. That is real -- the last four picks of an untraded draft are
    dead weight -- but it is also exactly where the SEPARATE keeper-cost bug
    documented at KEEPER_ROUNDS above bites: the owner's real final four in 2025
    were picks 70/71/78/90, worth +16.8/+16.1/+11.2/+2.2. Do not read "cost 0"
    as "keeping is always free"; read it as "these particular rounds are free."
    """
    source = projections if pool is None else pool
    board = _eligible_board(source)
    board = board.assign(vorp=vorp_column(board, kept_counts=kept_counts))
    # A position with no replacement level (goalies in skaters-only degraded
    # mode) yields NaN and would poison the mean, so it leaves the pricing pool.
    board = board.dropna(subset=["vorp"])
    board = board.sort_values("vorp", ascending=False).reset_index(drop=True)

    costs = {}
    for round_number in KEEPER_ROUNDS:
        start = (round_number - 1) * TEAM_COUNT
        picks = board.iloc[start : start + TEAM_COUNT]
        if len(picks) < TEAM_COUNT:
            required = max(KEEPER_ROUNDS) * TEAM_COUNT
            raise ValueError(f"Need at least {required} projected players to price keeper rounds")
        costs[round_number] = max(0.0, float(picks["vorp"].mean()))
    return costs


def vorp_column(projections: pd.DataFrame, pool: pd.DataFrame | None = None,
                kept_counts: dict[str, int] | None = None) -> pd.Series:
    """Value over positional replacement for every row: projected_total minus
    the position's replacement level. NaN where no level exists (position
    missing from the board), so degraded skaters-only exports still work.

    `pool` lets a caller rank one frame against another frame's replacement
    levels -- the keeper board ranks your own kept players, who are by
    definition not in the draft pool their value should be measured against.
    """
    levels = replacement_levels(projections if pool is None else pool, kept_counts)
    return pd.to_numeric(projections["projected_total"], errors="coerce") - (
        projections["position"].map(levels)
    )


def _eligible_board(frame: pd.DataFrame) -> pd.DataFrame:
    board = frame.copy()
    board["position"] = board["position"].map(_position)
    board["projected_total"] = pd.to_numeric(board["projected_total"], errors="coerce")
    return board[board["position"].isin(ELIGIBLE_POSITIONS)].dropna(
        subset=["projected_total"]
    )


def analyze_keepers(roster: list[dict], projections: pd.DataFrame,
                    pool: pd.DataFrame | None = None,
                    kept_counts: dict[str, int] | None = None) -> pd.DataFrame:
    """Return every Yahoo roster row with keeper values and four recommendations.

    `projections` is the frame roster players are matched against and must keep
    your own kept players on it, or they report "No projection match" -- the very
    players this exists to rate. `pool` is the frame replacement levels and pick
    costs are measured from, which should exclude every keeper in the league:
    what you get instead of keeping someone is a draft pick, and a draft pick
    cannot fetch a kept player.
    """
    board = _eligible_board(projections)
    value_pool = board if pool is None else _eligible_board(pool)
    levels = replacement_levels(value_pool, kept_counts)
    # Same levels on both sides of net_keeper_value: the keeper's surplus and
    # the surplus of the pick it costs. Mixing a VORP with an absolute total is
    # what made every keeper look like a mistake.
    pick_costs = round_pick_costs(value_pool, kept_counts=kept_counts)
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
