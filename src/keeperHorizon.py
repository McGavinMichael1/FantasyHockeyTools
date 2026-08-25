# Multi-year keeper valuation -- the "keeper horizon".
#
# The league rule is multi-year: you may keep the same player in consecutive
# seasons, paying your final four picks each year (owner, 2026-08-24). The
# keeper board's net_keeper_value answers a single-season question, so it
# prefers a 34-year-old to a 23-year-old of equal projection. This module
# prices the difference.
#
#     horizon_keeper_value = SUM(k=1..H) discount^k * S(age,k)
#                                        * [ A(age,k) * vorp1 - pick_cost_k ]
#
#     A(age,k) = product of ratio[age .. age+k-1]   cumulative age multiplier
#     S(age,k) = product of surv[age .. age+k-1]    cumulative survival
#
# Two properties are load-bearing:
#
#   * Survival multiplies the COST as well as the benefit. If the player is not
#     playing you are not keeping him, so you are not paying the picks.
#   * Both sides scale with the horizon. Multiplying only the benefit by five
#     years would make keeping look nearly free -- the same class of unit error
#     that produced the "keep nobody" bug documented at keeper.round_pick_costs.
#
# Pure functions, no IO: callers supply the history frames. Same discipline as
# frontend/src/lib, and for the same reason -- this is the testable surface.
#
# Spec: docs/superpowers/specs/2026-08-24-keeper-horizon-design.md

import numpy as np
import pandas as pd

HORIZON_YEARS = 5      # owner, 2026-08-24
DISCOUNT_RATE = 0.88   # owner, 2026-08-24
MIN_GP = 20            # "played a season", matching the draft ranker's floor

# Curves are only defined where the data supports them. Outside this range a
# lookup resolves to the nearest edge rather than extrapolating a trend that
# was never measured.
AGE_CLAMP = (20, 40)

# A bucket thinner than this does not get to emit its own estimate -- it
# borrows from the nearest bucket that clears the bar. Real goalie samples are
# n=3 at age 20 and n=5 at 39; a median over three players is not a curve.
MIN_BUCKET_N = 25

# Defaults per family. Goalies need wide bands because their per-age samples
# are single-digit outside 23-35; skaters have ~9,500 pairs and do not.
SKATER_BAND, SKATER_SMOOTH = 1, 3
GOALIE_BAND, GOALIE_SMOOTH = 3, 3

HISTORY_COLUMNS = ('playerId', 'season', 'gamesPlayed', 'fpPerGame',
                   'age_at_season_start')


def _prepare(history, exclude_transitions):
    """Attach each row's next CONSECUTIVE season, and its integer age bucket.

    A gap season is not a transition: a player who misses a year did not
    survive, and his before/after change is not an age-curve pair. Mirrors the
    `next_season == season + 1` guard in features/draft.py.
    """
    missing = [c for c in HISTORY_COLUMNS if c not in history.columns]
    if missing:
        raise ValueError(f"history is missing required columns: {missing}")

    df = history.loc[:, list(HISTORY_COLUMNS)].copy()
    df = df.sort_values(['playerId', 'season']).reset_index(drop=True)

    grouped = df.groupby('playerId')
    next_season = grouped['season'].shift(-1)
    consecutive = next_season == df['season'] + 1
    df['next_gp'] = grouped['gamesPlayed'].shift(-1).where(consecutive)
    df['next_fpPerGame'] = grouped['fpPerGame'].shift(-1).where(consecutive)

    # The final season present in the frame has no next season because the DATA
    # ends, not because the players did. Including it would read as a mass
    # extinction and collapse survival at whatever ages happen to sit there.
    df['evaluable'] = df['season'] < df['season'].max()
    if exclude_transitions:
        df.loc[df['season'].isin(exclude_transitions), 'evaluable'] = False

    # ROUND, not floor. age_at_season_start is the fractional age on Oct 1, so
    # rounding puts a player in the age he spends most of the season at. This
    # is not a stylistic choice: it is the convention the spec's measured table
    # was built with, verified 2026-08-24 by reproducing all ten of its
    # published (ratio, n) pairs exactly -- floor reproduces none of them. The
    # spec names this off-by-one as the most likely bug in the module.
    df['age_bucket'] = np.round(
        pd.to_numeric(df['age_at_season_start'], errors='coerce'))
    return df


def _band_key(age_bucket, band):
    """Left edge of the `band`-wide age group containing this bucket."""
    low = AGE_CLAMP[0]
    clamped = np.clip(age_bucket, low, AGE_CLAMP[1])
    return low + np.floor((clamped - low) / band) * band


def _assemble(values, counts, band, smooth):
    """Fill every age in AGE_CLAMP, borrow for thin buckets, then smooth.

    `values`/`counts` are keyed by band. A band below MIN_BUCKET_N takes the
    value AND the support of the nearest band that clears the bar, so a
    single-digit tail can never put its own number on the board.
    """
    ages = list(range(AGE_CLAMP[0], AGE_CLAMP[1] + 1))
    supported = {k: n for k, n in counts.items() if n >= MIN_BUCKET_N}
    if not supported:
        # Nothing is estimable. A neutral curve is the honest answer: it makes
        # the horizon a pure discount, not a fabricated aging story.
        return {age: 1.0 for age in ages}, {age: 0 for age in ages}

    raw, support = {}, {}
    for age in ages:
        key = float(_band_key(float(age), band))
        donor = key if key in supported else min(
            supported, key=lambda k: (abs(k - key), k))
        raw[age] = float(values[donor])
        support[age] = int(counts[donor])

    if smooth and smooth > 1:
        series = pd.Series([raw[a] for a in ages], index=ages)
        smoothed = series.rolling(smooth, center=True, min_periods=1).mean()
        raw = {age: float(smoothed[age]) for age in ages}
    return raw, support


def _curve(history, *, kind, min_gp, band, smooth, exclude_transitions):
    df = _prepare(history, exclude_transitions)
    eligible = df[df['evaluable'] & (df['gamesPlayed'] >= min_gp)].copy()

    if kind == 'survival':
        # Availability: did he clear the GP floor again the following season?
        # A missing next row is a 0, not a NaN -- absence is death.
        eligible['value'] = (eligible['next_gp'] >= min_gp).astype(float)
        aggregate = 'mean'
    else:
        # Production: median FP/game ratio across the transition, over players
        # who played both seasons. A median, not a mean, because a handful of
        # tiny-denominator seasons would otherwise dominate.
        eligible = eligible[(eligible['next_gp'] >= min_gp)
                            & (eligible['fpPerGame'] > 0)]
        eligible = eligible.assign(
            value=eligible['next_fpPerGame'] / eligible['fpPerGame'])
        aggregate = 'median'

    eligible = eligible.dropna(subset=['age_bucket', 'value'])
    if eligible.empty:
        return _assemble({}, {}, band, smooth)

    eligible['band'] = _band_key(eligible['age_bucket'].to_numpy(), band)
    grouped = eligible.groupby('band')['value']
    values = grouped.agg(aggregate).to_dict()
    counts = grouped.size().to_dict()
    return _assemble(values, counts, band, smooth)


def age_curve(history, *, min_gp=MIN_GP, band=SKATER_BAND, smooth=SKATER_SMOOTH,
              exclude_transitions=(), with_support=False):
    """Median FP/game ratio from each age to the next, keyed by integer age.

    `history` is any frame carrying HISTORY_COLUMNS -- player_seasons.csv and
    goalie_seasons.csv both qualify once shared.add_age_at_season_start has
    run. Expect the goalie curve to come out near 1.0 across the board: the
    goalie age ratio is flat and noisy, and survival carries their aging
    signal instead. That is an honest result, not a broken one.
    """
    values, support = _curve(history, kind='ratio', min_gp=min_gp, band=band,
                             smooth=smooth,
                             exclude_transitions=exclude_transitions)
    return (values, support) if with_support else values


def survival_curve(history, *, min_gp=MIN_GP, band=SKATER_BAND,
                   smooth=SKATER_SMOOTH, exclude_transitions=(),
                   with_support=False):
    """P(>= min_gp GP next season | >= min_gp GP this season), by integer age.

    This term, not the production term, is what separates a 34-year-old from a
    23-year-old: production decays ~9%/yr at 34 while availability decays much
    faster. Note it measures availability, not effectiveness -- a depth player
    scratching out 20 games counts as having survived.
    """
    values, support = _curve(history, kind='survival', min_gp=min_gp, band=band,
                             smooth=smooth,
                             exclude_transitions=exclude_transitions)
    return (values, support) if with_support else values


def _lookup(curve, age):
    if not curve:
        return 1.0
    keys = curve.keys()
    return float(curve[int(min(max(age, min(keys)), max(keys)))])


def horizon_multipliers(age, age_curve, survival_curve, *,
                        horizon=HORIZON_YEARS, discount=DISCOUNT_RATE):
    """Per-year (discount^k, S(age,k), A(age,k)) for k = 1..horizon.

    Exposed separately from horizon_value so the board and the advisor can show
    the breakdown rather than one opaque number -- the owner should be able to
    see WHY a 34-year-old's year-4 contribution rounds to nothing.

    Age alignment is spec-literal: A(age,1) = ratio[age], i.e. year 1 is itself
    age-adjusted. This is what reproduces the pre-registered multipliers (2.32
    at age 23, 1.23 at 34). It does apply one year of decay to a vorp1 that
    already reflects it, since the draft target is shift(-1) -- a known,
    recorded caveat, worth roughly 1.88x vs 1.67x. See PROJECT-PLAN's Learning
    Log entry for 2026-08-24.
    """
    # Rounded, matching the bucketing the curves were built with.
    bucket = int(np.round(age))
    out, survival, aging = [], 1.0, 1.0
    for k in range(1, int(horizon) + 1):
        survival *= _lookup(survival_curve, bucket + k - 1)
        aging *= _lookup(age_curve, bucket + k - 1)
        out.append((discount ** k, survival, aging))
    return out


def horizon_value(vorp1, age, pick_costs, age_curve, survival_curve, *,
                  horizon=HORIZON_YEARS, discount=DISCOUNT_RATE):
    """Discounted multi-year value of keeping this player, in VORP.

    `vorp1` is the existing year-1 value over replacement; `pick_costs` is the
    annual keeper cost, either a scalar or one value per year. At horizon=1,
    discount=1 and neutral curves this reduces exactly to today's
    raw_keeper_value - pick_cost, which is the point: a horizon of one year IS
    the current tool.

    Because the cost side is multiplied by survival too, this captures part of
    the walk-away option for free. The rest of that option -- the premium that
    would pay for a volatile 23-year-old over a stable 34-year-old -- needs
    prediction intervals we do not have, so this is a deliberate LOWER BOUND
    for young, volatile players.
    """
    multipliers = horizon_multipliers(age, age_curve, survival_curve,
                                      horizon=horizon, discount=discount)
    if np.isscalar(pick_costs):
        costs = [float(pick_costs)] * len(multipliers)
    else:
        costs = [float(c) for c in pick_costs]
        if len(costs) != len(multipliers):
            raise ValueError(
                f"pick_costs has {len(costs)} entries for a {len(multipliers)}"
                "-year horizon")

    return float(sum(
        discount_k * survival * (aging * float(vorp1) - cost)
        for (discount_k, survival, aging), cost in zip(multipliers, costs)))
