"""Tests for src/keeperHorizon.py -- the multi-year keeper valuation curves.

fht-quality-gates class (a) (keeper math), so these were written and watched
fail before the module existed. Synthetic frames only: the module does no IO,
and pinning it against real CSVs would make the tests depend on a rebuild.

Spec: docs/superpowers/specs/2026-08-24-keeper-horizon-design.md
"""

import numpy as np
import pandas as pd
import pytest

from src import keeperHorizon


# --- synthetic history builders -------------------------------------------

def _cohort(rows, start_id, age, ratio, survival, *, n=60, first_season=2000,
            fp=2.0, gp=82, dead_gp=10, drop_dead_row=False):
    """One cohort of n players observed at `age` in `first_season`.

    `survival` of them play >= 20 GP the following season at fpPerGame *
    `ratio`; the rest either play too few games (dead_gp) or vanish entirely
    (drop_dead_row) -- both must count as "did not survive".
    """
    survivors = int(round(n * survival))
    for i in range(n):
        pid = start_id + i
        rows.append(dict(playerId=pid, season=first_season, gamesPlayed=gp,
                         fpPerGame=fp, age_at_season_start=float(age)))
        if i < survivors:
            rows.append(dict(playerId=pid, season=first_season + 1, gamesPlayed=gp,
                             fpPerGame=fp * ratio,
                             age_at_season_start=float(age + 1)))
        elif not drop_dead_row:
            rows.append(dict(playerId=pid, season=first_season + 1,
                             gamesPlayed=dead_gp, fpPerGame=fp,
                             age_at_season_start=float(age + 1)))
    return rows


def _history(rows):
    return pd.DataFrame(rows, columns=['playerId', 'season', 'gamesPlayed',
                                       'fpPerGame', 'age_at_season_start'])


# Ratios and survivals chosen so every cohort clears MIN_BUCKET_N on BOTH
# sides: 60 players per age, and the thinnest survivor group is 60*0.50 = 30.
KNOWN_RATIO = {24: 1.02, 25: 0.98, 26: 0.94}
KNOWN_SURVIVAL = {24: 0.75, 25: 0.50, 26: 0.80}


def _known_history(**kwargs):
    rows = []
    for offset, age in enumerate(sorted(KNOWN_RATIO)):
        _cohort(rows, start_id=1000 * (offset + 1), age=age,
                ratio=KNOWN_RATIO[age], survival=KNOWN_SURVIVAL[age], **kwargs)
    return _history(rows)


def _flat(value, low=20, high=40):
    return {age: value for age in range(low, high + 1)}


# --- curve recovery: the off-by-one catcher -------------------------------

def test_age_curve_recovers_a_known_ratio():
    # 60 players enter at each of ages 24/25/26; the survivors' fpPerGame is
    # exactly fp * KNOWN_RATIO[age] the next season, so the median ratio at
    # each age must come back as that number. smooth=1 because a centred
    # 3-wide smoother would deliberately blur these into each other.
    curve = keeperHorizon.age_curve(_known_history(), band=1, smooth=1)
    for age, expected in KNOWN_RATIO.items():
        assert curve[age] == pytest.approx(expected, abs=1e-9)


def test_survival_curve_recovers_a_known_survival():
    # 45/60, 30/60, 48/60 survivors -> 0.75, 0.50, 0.80.
    curve = keeperHorizon.survival_curve(_known_history(), band=1, smooth=1)
    for age, expected in KNOWN_SURVIVAL.items():
        assert curve[age] == pytest.approx(expected, abs=1e-9)


def test_a_vanished_player_counts_as_not_surviving():
    # Same cohorts, but the non-survivors have no next-season row at all
    # rather than a short one. Absence is death, not missing data.
    curve = keeperHorizon.survival_curve(
        _known_history(drop_dead_row=True), band=1, smooth=1)
    for age, expected in KNOWN_SURVIVAL.items():
        assert curve[age] == pytest.approx(expected, abs=1e-9)


# --- alignment and bucketing ----------------------------------------------

def test_fractional_age_buckets_by_rounding_not_flooring():
    # age_at_season_start is the fractional age on Oct 1 (features/shared.py),
    # so a player at 24.6 spends most of the season at 25 and belongs there.
    #
    # This is the spec's named "most likely bug in the whole module", and the
    # convention is not a matter of taste: rounding reproduces all ten of the
    # spec's published (ratio, n) pairs exactly on the real table, and flooring
    # reproduces none of them (verified 2026-08-24).
    rows = []
    _cohort(rows, start_id=1, age=24, ratio=1.02, survival=1.0)
    base = _history(rows)

    low = base.assign(age_at_season_start=base['age_at_season_start'] + 0.4)
    assert keeperHorizon.age_curve(low, band=1, smooth=1)[24] == pytest.approx(1.02)

    high = base.assign(age_at_season_start=base['age_at_season_start'] + 0.6)
    curve = keeperHorizon.age_curve(high, band=1, smooth=1, with_support=True)
    values, support = curve
    assert support[25] >= keeperHorizon.MIN_BUCKET_N
    assert values[25] == pytest.approx(1.02)


def test_multiplier_lookup_rounds_the_board_age():
    # The board's age column is age_at_season_start + 1 and is fractional
    # (main.py). Lookup must use the same rounding the curves were built with,
    # or every player is priced off his neighbour's curve entry.
    age_c, surv_c = _flat(0.95), _flat(0.9)
    age_c[27], age_c[28] = 0.95, 0.5
    assert (keeperHorizon.horizon_multipliers(27.0, age_c, surv_c, horizon=1)
            == keeperHorizon.horizon_multipliers(27.4, age_c, surv_c, horizon=1))
    rounded_up = keeperHorizon.horizon_multipliers(27.6, age_c, surv_c, horizon=1)
    assert rounded_up[0][2] == pytest.approx(0.5)


def test_gap_season_contributes_no_ratio_and_no_survival():
    # A player who misses 2001 entirely and returns in 2002 did NOT survive,
    # and his 2000->2002 change is not an age-curve pair. Mirrors the
    # next_season == season + 1 guard in features/draft.py.
    rows = []
    _cohort(rows, start_id=1, age=30, ratio=1.0, survival=1.0)
    frame = _history(rows)
    gapped = pd.DataFrame([
        dict(playerId=9001, season=2000, gamesPlayed=82, fpPerGame=2.0,
             age_at_season_start=30.0),
        dict(playerId=9001, season=2002, gamesPlayed=82, fpPerGame=8.0,
             age_at_season_start=32.0),
    ])
    frame = pd.concat([frame, gapped], ignore_index=True)
    # The 4x jump would wreck a median that accepted it; 1.0 proves it didn't.
    assert keeperHorizon.age_curve(frame, band=1, smooth=1)[30] == pytest.approx(1.0)
    # 60 survivors out of 61 eligible at age 30.
    surv = keeperHorizon.survival_curve(frame, band=1, smooth=1)[30]
    assert surv == pytest.approx(60 / 61, abs=1e-9)


def test_final_season_rows_are_excluded_from_the_survival_denominator():
    # Every player plays 2000 and 2001 and survives. The 2001 rows (age 31)
    # have no next season because the DATA ends, not because the player did.
    # Counting them as deaths would drive survival to 0 -- the second most
    # likely bug in this module.
    rows = []
    _cohort(rows, start_id=1, age=30, ratio=1.0, survival=1.0)
    curve = keeperHorizon.survival_curve(_history(rows), band=1, smooth=1)
    assert curve[30] == pytest.approx(1.0)
    assert curve[31] != pytest.approx(0.0)


# --- the formula ----------------------------------------------------------

def test_horizon_one_with_neutral_curves_is_todays_net_keeper_value():
    # A horizon of one year IS the current tool. horizon=1, discount=1.0,
    # S=1, A=1  ->  vorp1 - pick_cost = 100.0 - 13.0 = 87.0 exactly.
    value = keeperHorizon.horizon_value(
        100.0, 27, 13.0, _flat(1.0), _flat(1.0), horizon=1, discount=1.0)
    assert value == pytest.approx(87.0, abs=1e-9)


def test_multipliers_are_spec_literal_products_from_age_through_age_plus_k():
    # A(age,k) = product of ratio[age .. age+k-1], so year 1 IS age-adjusted.
    # With ratio 0.9 and survival 0.8 everywhere, k=2 gives
    #   discount^2 = 0.88^2 = 0.7744, S = 0.8*0.8 = 0.64, A = 0.9*0.9 = 0.81
    mults = keeperHorizon.horizon_multipliers(30, _flat(0.9), _flat(0.8), horizon=2)
    assert mults[0] == pytest.approx((0.88, 0.8, 0.9))
    assert mults[1] == pytest.approx((0.7744, 0.64, 0.81))


def test_survival_discounts_the_cost_as_well_as_the_benefit():
    # If he is not playing you are not keeping him, so you are not paying the
    # picks. With vorp1 = 0 the whole value is the cost side, and halving
    # survival must halve it, not leave it untouched.
    kwargs = dict(horizon=1, discount=1.0)
    full = keeperHorizon.horizon_value(0.0, 30, 10.0, _flat(1.0), _flat(1.0), **kwargs)
    half = keeperHorizon.horizon_value(0.0, 30, 10.0, _flat(1.0), _flat(0.5), **kwargs)
    assert full == pytest.approx(-10.0)
    assert half == pytest.approx(-5.0)


@pytest.mark.parametrize('horizon', [1, 2, 3, 4, 5])
def test_a_pick_cost_strictly_lowers_the_value_at_every_horizon(horizon):
    # Synthetic costs on purpose: on the live 2026 board all four keeper
    # rounds price at 0.0 VORP, so a real-data version of this is vacuous.
    free = keeperHorizon.horizon_value(100.0, 26, 0.0, _flat(0.98), _flat(0.85),
                                       horizon=horizon)
    paid = keeperHorizon.horizon_value(100.0, 26, 12.0, _flat(0.98), _flat(0.85),
                                       horizon=horizon)
    assert paid < free


def test_pick_costs_accepts_a_per_year_sequence():
    scalar = keeperHorizon.horizon_value(
        100.0, 26, 5.0, _flat(1.0), _flat(1.0), horizon=3, discount=1.0)
    sequence = keeperHorizon.horizon_value(
        100.0, 26, [5.0, 5.0, 5.0], _flat(1.0), _flat(1.0), horizon=3, discount=1.0)
    assert scalar == pytest.approx(sequence)


# --- shape gates, on the spec's own measured table ------------------------

# The spec's measured skater curves (verified read-only 2026-08-24), linearly
# interpolated across the ages it does not list. Good enough to pin SHAPE;
# G-MULT proper runs against the real curves in the gate step.
_SPEC_RATIO = {21: 1.096, 23: 1.026, 24: 1.002, 27: 0.972, 30: 0.938,
               32: 0.927, 34: 0.909, 35: 0.881, 36: 0.914, 38: 0.839}
_SPEC_SURV = {21: 0.875, 23: 0.860, 24: 0.844, 27: 0.855, 30: 0.855,
              32: 0.793, 34: 0.778, 35: 0.688, 36: 0.640, 38: 0.529}


def _interpolated(table, low=20, high=40):
    keys = sorted(table)
    ages = list(range(low, high + 1))
    values = np.interp(ages, keys, [table[k] for k in keys])
    return dict(zip(ages, values))


def _total_multiplier(age, age_c, surv_c):
    return sum(d * s * a for d, s, a in
               keeperHorizon.horizon_multipliers(age, age_c, surv_c))


def test_multiplier_decreases_monotonically_in_age():
    age_c, surv_c = _interpolated(_SPEC_RATIO), _interpolated(_SPEC_SURV)
    totals = [_total_multiplier(age, age_c, surv_c) for age in range(24, 39)]
    assert all(later < earlier for earlier, later in zip(totals, totals[1:])), totals


def test_young_vs_old_multiplier_lands_near_the_pre_registered_ratio():
    # Pre-registered: 2.32 at age 23, 1.23 at age 34, a ratio of 1.88x.
    # Bands are loose because the curves here are interpolated from ten
    # published points rather than measured -- this pins the effect size's
    # order of magnitude, not the gate.
    age_c, surv_c = _interpolated(_SPEC_RATIO), _interpolated(_SPEC_SURV)
    young = _total_multiplier(23, age_c, surv_c)
    old = _total_multiplier(34, age_c, surv_c)
    assert 2.15 <= young <= 2.55
    assert 1.10 <= old <= 1.40
    assert 1.6 <= young / old <= 2.15


# --- banding, smoothing, clamping ----------------------------------------

def test_no_thin_bucket_reaches_the_output():
    # Goalie-shaped data: a fat middle and single-digit tails. Per-age goalie
    # samples are n=3 at 20 and n=5 at 39 in the real table, which is not
    # estimable -- the tails must borrow, never emit their own number.
    rows = []
    _cohort(rows, start_id=1, age=28, ratio=0.99, survival=0.9, n=200)
    _cohort(rows, start_id=5000, age=20, ratio=5.0, survival=0.1, n=3)
    frame = _history(rows)
    _, support = keeperHorizon.survival_curve(
        frame, band=3, smooth=3, with_support=True)
    assert min(support.values()) >= keeperHorizon.MIN_BUCKET_N
    # The absurd 5.0 ratio from the n=3 tail must not survive into the curve.
    ratios, _ = keeperHorizon.age_curve(frame, band=3, smooth=3, with_support=True)
    assert max(ratios.values()) < 2.0


def test_ages_outside_the_clamp_resolve_to_the_nearest_edge():
    age_c = _flat(1.0)
    age_c[40], age_c[20] = 0.5, 1.5
    surv_c = _flat(1.0)
    old = keeperHorizon.horizon_multipliers(47, age_c, surv_c, horizon=1)
    young = keeperHorizon.horizon_multipliers(15, age_c, surv_c, horizon=1)
    assert old[0][2] == pytest.approx(0.5)
    assert young[0][2] == pytest.approx(1.5)


def test_excluded_transitions_drop_those_feature_seasons():
    rows = []
    _cohort(rows, start_id=1, age=30, ratio=1.0, survival=1.0, first_season=2000)
    _cohort(rows, start_id=5000, age=30, ratio=1.0, survival=0.0,
            first_season=2019, n=200)
    frame = _history(rows)
    # With the 2019 transition in, age-30 survival is dragged toward 0.
    assert keeperHorizon.survival_curve(frame, band=1, smooth=1)[30] < 0.5
    # Excluding it restores the clean cohort.
    excluded = keeperHorizon.survival_curve(
        frame, band=1, smooth=1, exclude_transitions=(2019,))
    assert excluded[30] == pytest.approx(1.0)


def test_constants_match_the_owner_approved_design():
    # H = 5, discount = 0.88 (owner, 2026-08-24). Surfaced through
    # keeper.league_rules() so the advisor and frontend read one source.
    assert keeperHorizon.HORIZON_YEARS == 5
    assert keeperHorizon.DISCOUNT_RATE == 0.88
    assert keeperHorizon.MIN_GP == 20
