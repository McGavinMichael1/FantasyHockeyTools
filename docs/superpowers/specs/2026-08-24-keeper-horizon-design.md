# Multi-year keeper valuation (keeper horizon)

Date: 2026-08-24
Status: design approved, not implemented
Owner decisions captured: keeper tenure, horizon/discount, goalie treatment

## Problem

The keeper analyzer ranks your roster by `net_keeper_value`, a **single-season**
number: `projected_total - replacement_level - pick_cost`. The league rule is
multi-year — you may keep the same player in consecutive seasons, paying your
final four picks each year (owner, 2026-08-24) — so the tool is answering a
narrower question than the one the owner is actually deciding.

The symptom that prompted this: the board prefers Artemi Panarin (34) to Wyatt
Johnston / Dylan Guenther (23), which is correct for next season alone and
plausibly wrong for a keeper you can hold for five.

Four properties of the current pipeline all push that direction, and none are
bugs:

1. **No horizon.** The draft target is `target_fpPerGame = shift(-1)`
   (`src/features/draft.py:68`) — next season, full stop. `KEEPER_TENURE =
   "unknown"` (`src/keeper.py:33`) means the keeper math never asks either.
2. **Flat games played.** `projected_total = projected_fpPerGame * 78`
   (`main.py:200`) for every skater. Goalies get a real projected-GP term
   (`main.py:265-266`); skaters do not. Durability risk is priced at zero.
3. **Point estimates only.** `analyze_keepers` carries no variance column, so a
   tight 250 and a wide 250 are indistinguishable.
4. **Trees return the cohort mean.** Thin-résumé players land in leaves with
   mixed outcomes and receive the average, so the model structurally cannot call
   a breakout. The `>= 20 GP in both seasons` training filter also selects for
   players who stuck, muting the aging cliff at the other end.

This design fixes (1) only. (2) and (3) are separate, later work; see Non-goals.

## Approach

Chosen from three candidates (see Rejected alternatives): apply an **empirical
age curve** and an **empirical survival curve**, both derived from the 18
seasons already on disk, to the existing year-1 VORP. No model retraining, no
new data source, and the shipped draft ranker is untouched.

### The formula

```
horizon_keeper_value = Σ(k=1..H) discount^k · S(age, k) · [ A(age, k) · vorp₁ − pick_cost_k ]
```

where

- `H = 5`, `discount = 0.88` (owner, 2026-08-24)
- `A(age, k)` = cumulative age multiplier: the product of the per-age FP/game
  ratios from `age` through `age + k − 1`
- `S(age, k)` = cumulative survival: the product of the per-age probabilities of
  playing ≥20 GP the following season
- `pick_cost_k` = the annual keeper cost from `keeper.round_pick_costs`

**Survival multiplies the cost as well as the benefit.** If the player is not
playing you are not keeping him, so you are not paying the picks. This is a free
partial capture of the walk-away option (below).

**Both sides scale with the horizon.** Multiplying only the benefit by five
years would make keeping look nearly free. This is the same class of unit error
that already produced the "keep nobody" bug documented at
`keeper.round_pick_costs` — the one where a VORP was compared against an
absolute season total. Do not reintroduce it.

### The walk-away option is deliberately NOT modeled in v1

Because the decision is re-made annually, the strict value is
`Σ discount^k · E[max(·, 0)]`, not `Σ discount^k · max(E[·], 0)`. The difference
is an option premium that grows with variance, and it is precisely what would
pay for a volatile 23-year-old over a stable 34-year-old.

Computing it requires prediction intervals, which do not exist. **v1 therefore
reports a lower bound for young, volatile players, and says so.** A fabricated
variance term would be worse than a known-conservative number. Revisit after the
quantile-projection work.

## Measured inputs (verified 2026-08-24, read-only)

Sample sizes and curve shapes were checked before committing to the design.
`player_seasons.csv`: 16,271 rows, seasons 2008–2025, **9,525** age-curve pairs
(≥20 GP in both seasons). `goalie_seasons.csv`: 1,702 rows, **738** pairs.

Skaters, selected ages — `ratio` is the median `fpPerGame(a+1)/fpPerGame(a)`,
`surv` is P(≥20 GP next season | ≥20 GP this season):

| age | n | ratio | surv | surv n |
|----|-----|-------|-------|--------|
| 21 | 398 | 1.096 | 0.875 | 455 |
| 23 | 763 | 1.026 | 0.860 | 887 |
| 24 | 864 | 1.002 | 0.844 | 1024 |
| 27 | 817 | 0.972 | 0.855 | 956 |
| 30 | 608 | 0.938 | 0.855 | 711 |
| 32 | 417 | 0.927 | 0.793 | 526 |
| 34 | 266 | 0.909 | 0.778 | 342 |
| 35 | 190 | 0.881 | 0.688 | 276 |
| 36 | 126 | 0.914 | 0.640 | 197 |
| 38 |  46 | 0.839 | 0.529 |  87 |

Both curves behave as theory predicts: the ratio crosses 1.0 at age ~24 and
declines after; survival sits flat near 0.85 through 31 and then falls off a
cliff. **The survival term, not the production term, is what separates a
34-year-old from a 23-year-old** — production decays ~9%/yr at 34, but
availability decays much faster.

### Pre-computed expected effect (pre-registration)

Applying the formula to the measured curves at `H=5, discount=0.88`, the
horizon multiplier is:

- age 23: **2.32**
- age 34: **1.23**

A ratio of **1.88×**. Concretely: a 23-year-old needs only ~53% of a
34-year-old's year-1 VORP to be the better keep. This is recorded here **before
implementation** so the eyeball gate below is a real test and not a
rationalization of whatever the code emits. If the implementation produces
multipliers materially different from these, the implementation is wrong, not
the estimate.

### Goalies

Separate curves from `goalie_seasons.csv` (owner, 2026-08-24). Two things the
measurement showed that change how they must be built:

- **The goalie age ratio is essentially flat and noisy** — 0.95–1.01 from age 22
  through 40, with no detectable decline. Expect `A(age, k) ≈ 1.0` for goalies.
  That is an acceptable, honest outcome; **survival carries the entire goalie
  aging signal.**
- **Per-age samples are single-digit below 23 and above 35** (n=3 at age 20,
  n=5 at 39). Single-year buckets are not estimable there. Goalie curves must
  use **wide age bands** (suggest 3-year bands) plus smoothing, not per-year
  medians, and must clamp to a documented range.

The birthdate cache already covers goalie ids (extended by
`scripts/build_goalie_seasons.py`), so `shared.add_age_at_season_start` works on
both tables unchanged.

### Skater F/D split — deferred to v1.1, decision pre-loaded

Sample sizes support it (ages 20–36: D total 3,273, per-age median 190, min 46;
F total 6,252, per-age median 394, min 80), but the tails are thin enough to
need the same smoothing as goalies. Defenders are known to peak later, so the
split is real signal — it is simply second-order against the 1.88× effect above.
v1 ships a single skater curve. Revisit with the numbers already recorded here.

## Module design

**New: `src/keeperHorizon.py`** — pure functions, no IO, mirroring the
`frontend/src/lib` discipline for the same reason: this is the testable surface.

```python
def age_curve(history, *, min_gp=20, band=1, smooth=3) -> dict[int, float]
def survival_curve(history, *, min_gp=20, band=1, smooth=3) -> dict[int, float]
def horizon_multipliers(age, age_curve, survival_curve, *, horizon=5, discount=0.88)
    -> list[tuple[float, float, float]]   # per year: (discount^k, S, A)
def horizon_value(vorp1, age, pick_costs, age_curve, survival_curve,
                  *, horizon=5, discount=0.88) -> float
```

Callers supply the history frames; the module never reads a CSV. Age enters
already computed via `shared.add_age_at_season_start`, so `keeperHorizon` has no
dependency on the birthdate cache.

`horizon_multipliers` is exposed separately so the frontend and the advisor can
show the per-year breakdown rather than a single opaque number — the owner
should be able to see *why* a 34-year-old's year-4 contribution rounds to
nothing.

### Constants

`HORIZON_YEARS = 5` and `DISCOUNT_RATE = 0.88` live in `src/keeperHorizon.py`
and are surfaced through `keeper.league_rules()` alongside the existing keeper
rules, so the advisor and the frontend read one source.

`KEEPER_TENURE` in `src/keeper.py:33` changes from `"unknown"` to
`"multi_year_annual_cost"` — it is now answered.

## Integration

Additive only. Existing columns keep their exact current values.

- `keeper.analyze_keepers` gains `horizon_keeper_value` and
  `horizon_multiplier`. `raw_keeper_value` and `net_keeper_value` are unchanged.
- **Recommendation order switches to `horizon_keeper_value`** once the gates
  below pass. This is the behavioral change; everything else is display.
- `src/keeper_advisor.py:226` independently recomputes
  `raw_keeper_value - pick_cost`. It is a second implementation of the same
  formula and **must change in step**, or the advisor will argue against the
  board it is summarizing. Its `DECISION_COLUMNS` tuple
  (`src/keeper_advisor.py:37`) needs the new columns too.
- `api_export.py:276-277` exports the new fields; `frontend/src/app/keeper/
  page.tsx:36-37` renders the horizon value with the per-year breakdown and an
  explicit "5-yr" label, so a horizon number is never mistaken for a season
  total.
- `main.py` `runKeeper` prints `horizon_keeper_value` in the recommended-keepers
  table.

## Testing

Class (a) change per `fht-quality-gates` (keeper math) — tests first.

- **Curve recovery.** Synthesize a history with a known age curve and known
  survival, then assert `age_curve` / `survival_curve` recover it within
  tolerance. This is the test that catches an off-by-one in the age alignment,
  the most likely bug in the whole module.
- **Formula identities.** `horizon=1, discount=1.0, S≡1, A≡1` must reproduce
  exactly today's `net_keeper_value`. A horizon of one year is the current tool,
  and if it does not reduce to it, the generalization is wrong.
- **Monotonicity.** With the measured curves, the multiplier must decrease
  monotonically in age over 24–38.
- **Cost scaling.** A run with `pick_cost > 0` must produce a strictly lower
  value than the same run with `pick_cost = 0`, at every horizon.
- **No-regression.** Existing keeper tests stay green unchanged; the
  `best_available` fixture is untouched by this work.
- Goalie curves: assert the banding actually widens buckets at the tails
  (no single-digit-n estimate reaches the output).

## Gates

- **G-AGE** — the skater age curve peaks in 23–27 and declines after ~30. A
  curve that is flat or rising at 34 means delta-method survivorship bias won;
  debug before trusting. *(Pre-verified on the raw data above; the gate is that
  the implementation reproduces it.)*
- **G-SURV** — skater survival is clearly below 1.0 by the mid-30s. A curve near
  1.0 everywhere means the ≥20 GP threshold is too lax to see a cliff.
- **G-MULT** — computed multipliers match the pre-registered 2.32 (age 23) and
  1.23 (age 34) within a small tolerance.
- **G-FLIP (the one that matters)** — run the owner's real 2026 roster before and
  after. Guenther/Johnston must move up and Panarin down, **and the magnitude
  must be sane rather than absurd.** Direction alone is not a pass; a multiplier
  that ranks every 22-year-old above every established star has overshot.
- **G-NOCHANGE** — `draft_rankings.csv` and the existing keeper columns are
  byte-identical. This work is additive.

Record all gate results in `PROJECT-PLAN.md`'s Learning Log and update Current
Phase, per the campaign's standing practice.

## Known caveats

- **COVID seasons.** 2019-20 (~69 games) and 2020-21 (56 games) make the ≥20 GP
  threshold proportionally easier to clear, which likely inflates survival
  across those two transitions. Measure the effect; exclude or prorate if it is
  material. Not expected to change the shape, but it is unquantified today.
- **Survival is availability, not effectiveness.** A player who plays 20 games
  as a healthy scratch-adjacent depth piece counts as "survived." The age curve
  partly absorbs this via his falling FP/game, but the two terms are not fully
  independent and the product may double-count mildly at the old end. Direction
  of the error is conservative-for-young, so it does not threaten G-FLIP.
- **Replacement level is held constant across the horizon.** It is a
  league-structure property and roughly stable; modeling its drift is not worth
  the complexity.
- **The keeper-cost bug is untouched and still live.** `KEEPER_ROUNDS = (18, 17,
  16, 15)` understates cost when picks are traded (OPEN-QUESTIONS #1b). This
  design multiplies whatever `round_pick_costs` returns across five years, so it
  **propagates that understatement** rather than fixing it. Fixing it is
  separate work and would raise the cost side at every horizon year.

## Non-goals (explicitly out of scope for v1)

- Prediction intervals / quantile projections, and therefore the option premium.
- A skater games-played model to replace the flat `× 78`.
- Retraining the draft ranker on any multi-season target.
- The traded-pick keeper-cost fix (OPEN-QUESTIONS #1b).

## Precursor task

**Residual audit**, before implementation. Score the validation seasons with the
shipped `models/draft/model.pkl`, bucket signed residuals by age band ×
`career_games` band, and record the table. Purpose: if the model systematically
under-predicts 22-year-olds at year 1, this design compounds that bias five
years deep and multiplies the error instead of exposing it. Half an hour;
`model.pkl` and `player_seasons.csv` are both on disk. If the skew is large, the
age curve must be applied to a bias-corrected year-1 value, not the raw one.

## Rejected alternatives

- **Recursive re-prediction** — feed year 1's output back in, roll age forward,
  re-predict ×5. `avgIcetime`, `PP_share`, `xGoalsSurplus`, `highDangerShare`
  and `avgGameScore` cannot be regenerated from a PPG prediction, so they would
  be frozen while uncalibrated error compounds five deep. Nothing to validate it
  against.
- **Retraining on a multi-season target** (label = discounted sum of the next 3
  seasons). Statistically cleanest, but it needs three future seasons per row so
  it burns the recent end of the training data — the end that matters most — it
  conflates "will he produce" with "will he still be playing", and it forks or
  replaces the shipped ranker, forcing a full re-gate against both baselines.
  Reconsider only if the empirical-curve approach fails G-FLIP.
