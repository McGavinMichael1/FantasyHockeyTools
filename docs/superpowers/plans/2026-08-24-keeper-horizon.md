# Keeper Horizon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the keeper analyzer answer the multi-year question the league rule actually poses. Apply an empirical age curve and an empirical survival curve — both derived from the 18 seasons already on disk — to the existing year-1 VORP, and switch the keeper recommendation order to the resulting `horizon_keeper_value`.

**Architecture:** A new pure-function module `src/keeperHorizon.py` (no IO — callers supply the history frames, mirroring the `frontend/src/lib` discipline for the same reason: it is the testable surface) computes two curves from `player_seasons.csv` / `goalie_seasons.csv` and folds them into a discounted five-year sum. `src/keeper.py` gains two new columns and a new sort key; `keeper_advisor.py`, `main.py`, `api_export.py` and the keeper page follow. Nothing retrains, no new data source, and the shipped draft ranker is untouched.

**Tech Stack:** Python 3, pandas, pytest; TypeScript + `node --test` on the frontend. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-24-keeper-horizon-design.md`

## The formula

```
horizon_keeper_value = Σ(k=1..H) discount^k · S(age, k) · [ A(age, k) · vorp₁ − pick_cost_k ]

H = 5, discount = 0.88            (owner, 2026-08-24)
A(age, k) = Π(j=0..k-1) ratio[age+j]     cumulative age multiplier
S(age, k) = Π(j=0..k-1) surv[age+j]      cumulative survival
```

Two properties that are load-bearing and easy to break:

- **Survival multiplies the cost as well as the benefit.** If the player is not playing you are not keeping him, so you are not paying the picks.
- **Both sides scale with the horizon.** Multiplying only the benefit by five years would make keeping look nearly free. That is the same class of unit error that produced the "keep nobody" bug documented at `keeper.round_pick_costs`. Do not reintroduce it.

## Global Constraints

- **Always invoke `.\.venv\Scripts\python.exe` explicitly.** System `python` on this machine may resolve to an unrelated interpreter.
- **This is `fht-quality-gates` class (a)** (keeper math), the highest bar. Strict TDD: write the test, watch it fail, then write the code.
- **No new dependencies.** Nothing here needs one; adding one triggers the class (f) freeze-the-pins gate.
- **Never retrain the draft model.** `main.py train-draft` would change `draft_rankings.csv` values and break G-NOCHANGE. The residual audit fits in memory and never calls `draftModel.save()`.
- **Never touch `season.DRAFT_TEST_SEASON` (2024).** The one held-out look was spent by the 2025 mock draft.
- **Additive only.** `raw_keeper_value`, `net_keeper_value`, `pick_cost`, `replacement_level` and every `draft_rankings.csv` column keep their exact current values. The sort key is the one behavioural change.
- **The traded-pick keeper-cost bug (OPEN-QUESTIONS #1b) is NOT in scope.** This design multiplies whatever `round_pick_costs` returns across five years, so it *propagates* that understatement. Say so in the docs; do not fix it here.
- **Model `.pkl` files and everything under `data/` are gitignored.** Never `git add` them.
- **Test style:** hand-computed expected values in a comment above the assertion, matching `tests/test_fantasyPoints.py`.
- Full suite green before every commit: `.\.venv\Scripts\python.exe -m pytest -q` — baseline is **213 passed, 0 failed** (verified 2026-08-24). Frontend baseline: 133 unit tests.

## Decisions already taken (do not relitigate)

1. **Age alignment is spec-literal.** `A(age,1) = ratio[age]`, i.e. year 1 *is* age-adjusted. This reproduces the pre-registered multipliers 2.32 (age 23) / 1.23 (age 34) and is what makes G-MULT a real test. It does apply one year of decay to a `vorp₁` that already reflects it — a known ~1.88× vs ~1.67× difference. That is a **documented caveat and a follow-up**, not a silent deviation. Owner-confirmed 2026-08-24.
2. **The residual audit uses an honest train-only refit.** The shipped `models/draft/model.pkl` is refit on train+val (`src/models/draft.py:194-195`), so scoring 2022–23 off it is in-sample and would understate the young-player bias the audit exists to find. Owner-confirmed 2026-08-24.
3. **Ranking prices the cost side at the mean of the four keeper-round costs.** Round assignment happens after the sort, so a per-round cost cannot feed the sort without circularity. Every candidate is priced identically and comparably; the round assignment stays display-only.
4. **No skater F/D split in v1.** Sample sizes support it (ages 20–36: D 3,273 pairs, F 6,252) but the tails need the same smoothing as goalies, and the effect is second-order against 1.88×. Revisit in v1.1 with the numbers recorded in the spec.

---

### Task 1: Residual audit (spec precursor)

The spec calls for this **before** implementation: if the ranker systematically under-predicts 22-year-olds at year 1, this design compounds that bias five years deep and multiplies the error instead of exposing it.

**Files:**
- Create: `scripts/audit_draft_residuals.py`
- Modify: `PROJECT-PLAN.md` (Learning Log)

- [ ] **Step 1: Write the audit script**

Read-only with respect to every artifact on disk. Load features with `main.loadPlayerSeasonFeatures()` (`main.py:115-124`) — it reads the cached CSV and never rebuilds from the 2.6 GB MoneyPuck history.

```python
payload = draftModel.load()
params  = payload['model'].get_params()   # these ARE search.best_params_ (model is best_estimator_)
# refit XGBRegressor(**params) on season <= season.DRAFT_TRAIN_MAX_SEASON (2021)
# score season.DRAFT_VAL_SEASONS (2022, 2023)
# eligibility filter must match src/models/draft.py:106-110 exactly:
#   gamesPlayed >= 20 AND target_gamesPlayed >= 20 AND target_fpPerGame.notna()
```

Bucket signed residuals (`target_fpPerGame − prediction`) by age band × `career_games` band and print the table with per-cell n. Never call `draftModel.save()`.

- [ ] **Step 2: Record the table and apply the decision rule**

Append the table to the Learning Log. **If 22–24-year-olds show a materially negative mean residual**, the age curve must be applied to a bias-corrected `vorp₁` rather than the raw one — record the finding and **stop for an owner decision before Task 3**. If the skew is small, record it and continue.

---

### Task 2: Tests for `src/keeperHorizon.py` (red first)

**Files:**
- Create: `tests/test_keeper_horizon.py`

Synthetic frames only — no CSV reads. Follow the module-level row-builder convention (`_season_row(...)` in `tests/test_draft_features.py:7-25`).

- [ ] **Step 1: Curve recovery**

Synthesize a history with a known per-age ratio and known survival; assert `age_curve` / `survival_curve` recover them within tolerance. The spec names the age-alignment off-by-one as the most likely bug in the whole module; this is the test that catches it.

- [ ] **Step 2: Pin the age bucketing**

`age_at_season_start` is fractional (Oct-1 convention, `src/features/shared.py:36-37`) and the projection board's `age` is `age_at_season_start + 1` (`main.py:199`). Pin `floor()` as the bucket rule, and pin that the **board** age is what gets looked up — in both curve construction and evaluation.

- [ ] **Step 3: Gap-season guard**

A player who misses a season did **not** survive and contributes no ratio pair. Mirrors the `.where(next_season == season + 1)` guard at `src/features/draft.py:66-74`.

- [ ] **Step 4: Survival denominator excludes the final season in the frame**

Otherwise "no next row" is counted as death and survival collapses. This is the second-most-likely bug in the module.

- [ ] **Step 5: Formula identity**

`horizon=1, discount=1.0, S≡1, A≡1` must reproduce today's `raw_keeper_value − pick_cost` exactly. A horizon of one year *is* the current tool; if it does not reduce to it, the generalization is wrong.

- [ ] **Step 6: Monotonicity, cost scaling, goalie banding**

- With the measured curves the multiplier decreases monotonically over ages 24–38.
- `pick_cost > 0` gives a strictly lower value than `pick_cost = 0` at every horizon. **Use synthetic costs** — against the live board all four keeper rounds currently price at 0.0 (`src/keeper.py:188-195`), so a real-data test would be vacuous.
- No emitted goalie bucket is backed by fewer than `MIN_BUCKET_N` observations; ages outside `AGE_CLAMP` resolve to the nearest edge.

---

### Task 3: `src/keeperHorizon.py`

**Files:**
- Create: `src/keeperHorizon.py`

- [ ] **Step 1: Constants and signatures**

```python
HORIZON_YEARS = 5
DISCOUNT_RATE = 0.88
MIN_GP        = 20
AGE_CLAMP     = (20, 40)   # outside -> nearest edge, documented
MIN_BUCKET_N  = 25         # a thinner bucket widens/borrows rather than emitting

def age_curve(history, *, min_gp=20, band=1, smooth=3, exclude_transitions=()) -> dict[int, float]
def survival_curve(history, *, min_gp=20, band=1, smooth=3, exclude_transitions=()) -> dict[int, float]
def horizon_multipliers(age, age_curve, survival_curve, *, horizon=5, discount=0.88) \
        -> list[tuple[float, float, float]]     # per year k: (discount**k, S, A)
def horizon_value(vorp1, age, pick_costs, age_curve, survival_curve, *,
                  horizon=5, discount=0.88) -> float
```

`history` is any frame carrying `playerId, season, gamesPlayed, fpPerGame, age_at_season_start`. Both `player_seasons.csv` and `goalie_seasons.csv` qualify after `shared.add_age_at_season_start`, which already works on goalie ids because `scripts/build_goalie_seasons.py` extends the birthdate cache. `pick_costs` accepts a scalar (constant annual cost) or a per-year sequence.

`horizon_multipliers` is exposed separately so the frontend and the advisor can show the per-year breakdown rather than one opaque number — the owner should be able to see *why* a 34-year-old's year-4 contribution rounds to nothing.

- [ ] **Step 2: Curve construction**

- `ratio` = median `fpPerGame(a+1) / fpPerGame(a)` over consecutive seasons with ≥`min_gp` in both; guard `fpPerGame > 0`.
- `surv` = P(≥`min_gp` GP next season | ≥`min_gp` GP this season).
- Skaters: `band=1, smooth=3`. **Goalies: `band=3, smooth=3`** — per-age goalie samples are single-digit below 23 and above 35 (n=3 at 20, n=5 at 39), so single-year buckets are not estimable there. Expect goalie `A ≈ 1.0`; that is an honest outcome, and survival carries the entire goalie aging signal.

- [ ] **Step 3: COVID measurement**

Build both curves with and without the 2019 and 2020 feature-season transitions — the ~69- and 56-game seasons make the ≥20 GP threshold proportionally easier to clear and likely inflate survival across those two transitions. Record the delta in the Learning Log; exclude via `exclude_transitions` **only if material**.

---

### Task 4: `src/keeper.py` integration

**Files:**
- Modify: `src/keeper.py`, `tests/test_keeper.py`

- [ ] **Step 1: Constants (test first — this one goes red immediately)**

`tests/test_keeper.py:7` pins the exact `league_rules()` dict, so it fails the moment a key is added. Update it first.

- `KEEPER_TENURE` (`src/keeper.py:33`): `"unknown"` → `"multi_year_annual_cost"` — it is answered now.
- `league_rules()` (`:109`) surfaces `horizon_years` and `discount_rate` from `keeperHorizon`, so the advisor and the frontend read one source.

- [ ] **Step 2: `analyze_keepers` gains the horizon columns**

New signature: `analyze_keepers(roster, projections, pool=None, kept_counts=None, horizon_curves=None)`, where `horizon_curves` is `{"skater": {"age": …, "survival": …}, "goalie": {…}}`.

- **`None` → new columns are `pd.NA` and the sort is unchanged.** This is what keeps every existing keeper test green, and it is the same degrade-loudly-not-fatally pattern the goalie board already uses (`main.py:282-285`).
- Supplied → compute per matched row from the board's `age` column (already splatted onto the row by `row.update(player)` at `:294`) and the position's curve family.
- New columns: `horizon_keeper_value`, `horizon_multiplier`, `horizon_pick_cost`, and `horizon_breakdown` (one JSON cell per row, same pattern as the existing `factor_1..6` columns at `main.py:230-235`).

- [ ] **Step 3: Switch the recommendation order**

The sort at `src/keeper.py:309-312` moves to `horizon_keeper_value`, keeping the existing tiebreakers (`projected_total`, `playerId`). Note that today `pick_cost` is applied *after* selection and never affects the top-4 set; with the horizon value it does, because the horizon value is cost-inclusive. `raw_keeper_value` and `net_keeper_value` are unchanged.

---

### Task 5: `src/keeper_advisor.py` in step

`_scenario_sets` (`:201-234`) is a **second implementation of the same formula** — it independently recomputes `raw_keeper_value - pick_cost` at `:226`. It must change in step or the advisor will argue against the board it is summarizing.

**Files:**
- Modify: `src/keeper_advisor.py`, `tests/test_keeper_advisor.py`

- [ ] **Step 1: Columns and ordering**

- `DECISION_COLUMNS` (`:37-40`) gains the three new numeric columns.
- The scenario sort key (`:211-216`) must match `analyze_keepers`' new key exactly — these two orderings are already required to be in lockstep.
- **`horizon_keeper_value` is already cost-inclusive. Do not subtract `pick_cost` from it again.** That is the same class of unit error as the "keep nobody" bug.

- [ ] **Step 2: Tenure string**

`tests/test_keeper_advisor.py:126` asserts `keeper_tenure == "unknown"` — update it.

---

### Task 6: `main.py runKeeper`

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Build the curves once and pass them down**

`runKeeper` (`main.py:375-437`) already loads `player_seasons.csv` and `goalie_seasons.csv` at `:403-425` for the advisor context. Hoist that load **above** the `analyze_keepers` call, run `shared.add_age_at_season_start` on both frames, build the curves once, pass them as `horizon_curves`, and reuse the same frames for the advisor context. Missing history → warn loudly, pass `None`, keep today's behaviour.

- [ ] **Step 2: Print the horizon value**

Add `horizon_keeper_value` (and the multiplier) to the recommended-keepers table at `:432-437`.

---

### Task 7: Export and frontend

**Files:**
- Modify: `api_export.py`, `frontend/src/types/player.ts`, `frontend/src/app/keeper/page.tsx`
- Create: `frontend/src/lib/keeperHorizon.ts`, `frontend/src/lib/keeperHorizon.test.ts`
- Modify: `tests/test_api_export_keeper.py`

- [ ] **Step 1: Export**

`build_keeper_section()` (`api_export.py:249-308`) emits the new fields through the existing `_optional_number` helper (NaN → `null`).

- [ ] **Step 2: Frontend**

- `frontend/src/types/player.ts:90-105` — add the fields as `number | null`.
- `frontend/src/app/keeper/page.tsx` — the headline becomes the horizon value under an explicit **"5-yr keep value"** label, with `net_keeper_value` retained as a "next season" secondary, plus the per-year breakdown. A horizon number must never be mistaken for a season total.
- **Guard the new fields with null checks.** The existing card already calls `.toFixed()` unguarded on fields the export can emit as `null` (`:36-37`, `:43-51`) — do not add a fourth instance of that latent crash.
- **Per the standing rule, new logic goes in `frontend/src/lib`, not the component.** Breakdown formatting and horizon labels live in `keeperHorizon.ts` with a `node --test` companion, since `src/lib` is the only testable surface (the runner is bare `node --test` with no DOM).

Noted but **out of scope**: `page.tsx:50` hardcodes "78-game proj.", already wrong for goalies (their total is `fp/gp × min(gp_w3, 65)`); `page.tsx:161` hardcodes `[18, 17, 16, 15]` rather than reading the rounds from data.

---

### Task 8: Gates and recording

- [ ] **Step 1: Curve gates**

- **G-AGE** — the skater age curve peaks in 23–27 and declines after ~30. Flat or rising at 34 means delta-method survivorship bias won; debug before trusting.
- **G-SURV** — skater survival is clearly below 1.0 by the mid-30s. Near 1.0 everywhere means the ≥20 GP threshold is too lax to see the cliff.
- **G-MULT** — computed multipliers match the pre-registered **2.32** (age 23) and **1.23** (age 34) within a small tolerance. Materially different means the implementation is wrong, not the estimate.

- [ ] **Step 2: G-FLIP — the one that matters**

Run the owner's real 2026 roster before and after. Guenther/Johnston must move up and Panarin down, **and the magnitude must be sane rather than absurd.** Direction alone is not a pass: a multiplier that ranks every 22-year-old above every established star has overshot. Surface the actual player list and their values, not just the margin.

**Operational note:** this needs `main.py keeper`, which hits Yahoo OAuth and can block on stdin in a non-interactive shell. Run it in a real terminal.

- [ ] **Step 3: G-NOCHANGE**

Hash `data/processed/draft_rankings.csv` before and after, re-run `main.py draft`, confirm byte-identical. Confirm the pre-existing keeper columns are unchanged and `tests/fixtures/best_available_cases.json` is untouched.

- [ ] **Step 4: Record**

Record every gate result, the COVID measurement, and the year-1 double-count caveat in `PROJECT-PLAN.md`'s Learning Log, and update Current Phase. Update `.claude/skills/fht-draft-campaign` and CLAUDE.md's Known Issues if the keeper section is now stale.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q                     # 213 baseline, then after
.\.venv\Scripts\python.exe scripts/audit_draft_residuals.py
.\.venv\Scripts\python.exe main.py draft                    # G-NOCHANGE: hash before/after
.\.venv\Scripts\python.exe main.py keeper                   # G-FLIP (interactive: Yahoo OAuth)
cd frontend; npm run typecheck; npm run test:unit; npm run build
```
