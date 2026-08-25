# Deployment and luck features — design (2026-08-24)

Adding two feature families to the pickup/cooling models and the draft ranker:

- **Deployment** — power-play ice time (PP TOI), and whether it is trending up.
- **Luck** — PDO, split into its two halves rather than summed.

Both are `fht-research-frontier` item 2 ("trend and deployment features"), which
PROJECT-PLAN calls *"the most likely source of real signal, ahead of more tuning."*

---

## 1. Why these two, and why now

The pickup model's features are all **levels**: rolling means of production, possession
and ice time. Nothing in the current set answers either of the two questions that
actually separate a waiver-wire gem from a player having a good week:

| Question | Current feature that answers it |
|---|---|
| Did this player's *role* just change? | none |
| Is this player's production *sustainable*? | `xgoals_surplus` — partially, individual finishing only |

The canonical documented miss is in the repo already: `backtest.KNOWN_PICKUPS` lists
`'Darren Raddysh': 'Hedman injury opened PP1 mid-season, 70P'`. A PP1 promotion is the
classic breakout signal, and no feature represents power-play deployment today.

## 2. PP TOI

**Source:** `icetime` on the `5on4` situation row. Already in `GAME_COLUMNS` — this
family needs **no new MoneyPuck columns**, only a merge onto the `all` row using the
same mechanism `moneypuckGamePoints` already uses for PPP.

**Undercount, accepted:** 5-on-3 time lands in MoneyPuck's `other` bucket, so PP TOI
undercounts by the same small margin and for the same reason PPP does
(`fantasyPoints.py:51`). Consistent with the existing documented approximation; not a
new class of error.

**Modelled as a share, not just a level.** `pp_toi_share = powerPlayIcetime / icetime`.
A fourth-liner with 1:30 of PP time is a different signal from a first-liner with the
same 1:30 — the share separates them, the level does not. Both are kept; the model
picks.

**The delta is the point.** A rolling PP-TOI *level* cannot distinguish "has always been
a PP1 guy" from "was promoted to PP1 three games ago." Only the second is a breakout
signal, and only `rolling_5 − rolling_20` expresses it. Same treatment is applied to
`icetime` and `game_fantasy_points`, per research-frontier item 2's first step.

## 3. PDO — split, not summed

PDO = on-ice SH% + on-ice SV%. **The two halves have completely different fantasy
relevance under this league's scoring path, and summing them destroys the useful one.**

- **On-ice SH%** — real signal. A player's assists depend on teammates converting shots
  while he is on the ice. High on-ice SH% means his assist rate is running ahead of
  process, and it regresses. `xgoals_surplus` covers *his own* finishing luck; nothing
  covers teammate-conversion luck. This is the genuinely new information.
- **On-ice SV%** — near-dead weight *here*. It reaches fantasy points only through
  plus/minus, and `moneypuckGamePoints` does not compute plus/minus at all
  (`fantasyPoints.py:1-4`, the documented ~5% approximation). It has no path to the
  label except noise and team quality.

So: `onice_shooting_pct` and `onice_save_pct` ship as **separate** features. Summed
`pdo` is computed for the eyeball gate and the draft board, and is deliberately named
outside the `rolling_` prefix so `pickupFeatureCols`' allowlist does not enrol it — a
sum of two features already present adds a collinear column and nothing else.

On-ice SV% is included as a feature rather than excluded, so the data settles it once
instead of the argument above settling it by assertion. Pre-registered prediction: it
lands in the bottom half of `reports/pickup_feature_importance.png`.

**Also ship the xG-adjusted version.** `OnIce_F_goals − OnIce_F_xGoals` is on-ice
shooting luck corrected for shot quality: it regresses like on-ice SH% but does not
punish a player whose line generates low-percentage looks. Expected to beat raw on-ice
SH%; both ship, the model chooses.

### 3.1 Ratio of sums, never mean of ratios

**The single detail that decides whether this works.** A player is on the ice for ~10–25
shots per game. A per-game on-ice SH% is mostly denominator noise, and a rolling *mean
of per-game ratios* weights a 6-shot game identically to a 25-shot game.

Every on-ice percentage is therefore computed as `rolling_sum(goals) /
rolling_sum(shots)`. This does **not** fit `buildRollingFeatures`' existing
`.rolling().mean()` loop, so it needs its own block — appending these columns to
`all_window_stats` would silently produce the wrong statistic.

Consequences:
- Windows are **10 and 20 only**. Five games is ~60 on-ice shots; the estimate is
  worthless there.
- `min_periods=window` (a partial window has an even smaller denominator).
- Rows with fewer than **60** on-ice shots behind the estimate get `NaN`, not a number
  nobody should trust. XGBoost handles NaN natively — already relied on in
  `draft._feature_matrix`.

### 3.2 Even strength only

PDO is conventionally a 5v5 statistic. Computed off the `all` rows, power-play time
systematically inflates on-ice SH% for exactly the players who get PP1 minutes — which
turns the luck feature into a **deployment proxy**, double-counting what §2's features
already say. So the on-ice counts are merged from the `5on5` rows, using the same
per-situation merge as PPP.

This requires widening `GAME_COLUMNS` by five columns (verified present in
`data/raw/moneypuck_current.csv`): `OnIce_F_goals`, `OnIce_F_shotsOnGoal`,
`OnIce_F_xGoals`, `OnIce_A_goals`, `OnIce_A_shotsOnGoal`.

## 4. The draft side wants a residual, not a level

The draft model's strongest input is `fpPerGame` — last season's actual production.
PDO's *entire* marginal contribution is telling the model **that number was inflated**.
A raw on-ice SH% level cannot say that; a deviation from the player's own baseline can.

`onice_sh_luck = this season's on-ice SH% − mean of the player's prior 3 seasons`.
Deviation from his *own* history beats deviation from the league mean, because on-ice
SH% has a real talent component (elite linemates genuinely convert more) and only the
transient part regresses. First-season players get `NaN` — same as `fp_delta`, and
correct: a rookie has no baseline to deviate from.

**Free diagnostic:** `draft.train()` already prints standardized Ridge coefficients for
sign-checking. `onice_sh_luck` **must** come out negative — luck above your own baseline
predicts a *drop* in next-season FP/g, holding this season's FP/g constant. A positive
coefficient means the residual is behaving as a talent proxy and the feature is wrong.

## 5. Evidence bar

Per `fht-quality-gates` §2 and `fht-research-frontier` methodology (a)–(c):

- **Predictions written down before training** (Task 1), never after.
- **PP TOI and PDO get separate retrain gates.** Landing both and retraining once cannot
  attribute the change to either. Sequence: PP TOI → retrain → record → PDO → retrain →
  record.
- **Product metric decides**, not global AUC: `backtest.py` top-15 hit rate across all
  five `DEFAULT_DATES` for pickups, val Spearman for draft.
- **The 2024 draft test season stays untouched.** The 2025 mock-draft look is already
  spent, so draft-side evidence stands on val Spearman (2022–2023) alone.

Numbers to beat, from `fht-quality-gates` §3 (July 6 2026 regression conversion):

| Model | Metric | Current |
|---|---|---|
| Pickup | val Spearman | 0.6214 |
| Pickup | val AUC vs `is_heating_up` | 0.8465 |
| Cooling | val Spearman | 0.6063 |
| Cooling | val AUC-equivalent | 0.7673 |
| Spot-check | top-15 hit rate per date | 67/60/47/53/47 (mean 55%) |
| Spot-check | 25 simulated adds | 60% hit, 2.83 FP/g (chaser 40%, 2.35) |
| Draft | val Spearman vs Baselines A/B | **captured in Task 1** — not recorded anywhere |

**Where this most likely pays: the cooling model.** Cooling is the weaker model (0.6063)
and "running hot, due to regress" is literally what an on-ice shooting-percentage
residual measures. Pickups may see little. That asymmetry is part of the
pre-registration.

## 6. Out of scope

- Tuning the cooling model (research-frontier item 1) — separate change, would confound
  the attribution these gates depend on.
- Optuna (item 4) — dependency change, unrelated.
- PP *unit* assignment (PP1 vs PP2) — no data source exists in this repo; PP TOI share is
  the available proxy and the point of using it.
- Goalie features — `GOALIE_SEASON_COLUMNS` is a separate path and PDO is a skater stat.
