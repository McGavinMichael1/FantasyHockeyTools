# Handoff — draft validation + live board (2026-07-20)

Branch `feat/draft-validation-and-live-board`, 16 commits, pushed. Suite: **141 pytest,
58 frontend, typecheck clean.** Everything below was verified on that branch today.

**Read first:** `CLAUDE.md`, then the skill matching your task (`.claude/skills/fht-*`), then
PROJECT-PLAN's Current Phase. This covers only what those don't.

Supersedes `2026-07-20-post-sustainability-handoff.md`, whose recommended items #1 (CI), #2
(mock draft), #3 (test-2024), #5 (live draft mode) are now done, and whose framing of #2 and #3
as separate items was wrong — they are the same look.

---

## The headline: the board does not beat hand-drafting

**2025 mock draft, keepers correctly excluded: board 2,662.5 FP vs the owner's real draft
2,709.8 FP. −47.3 FP (−1.75%), board won 7 of 14 picks.**

Pre-registered bands put that at **inconclusive** (−5% to +5%). The held-out look is spent.

Do not present the board as an authority that overrides the owner. On the one honest test
available it drafts about as well as he does. What it legitimately offers is consistency — it
does not tire in round 12, applies the same standard at pick 3 and pick 140 — plus the live
mode's VORP recomputation, which no human tracks unaided.

Full record: `docs/superpowers/plans/2026-07-20-mock-draft-preregistration.md` (prediction,
bands, gates, both void runs) and PROJECT-PLAN's Learning Log.

### It took three attempts and the first two were both wrong

| | Result | Why it was wrong |
|---|---|---|
| Prediction | +15% | Written down first, so it could be wrong in public |
| Run 1 | +29.3% | **VOID** — keepers left in the pool; the board drafted McDavid, MacKinnon, Kucherov and five others who were never available |
| Run 2 | **−1.75%** | Correct. Keepers derived from each team's final four picks |

The owner caught run 1 by reading the roster. **Every automated gate passed it.** The eyeball
gate was looking for absurd *players*; a roster of McDavid and Kucherov looks entirely
plausible — the absurdity was in their *availability*.

---

## What is now true that wasn't

- **CI exists** (`.github/workflows/ci.yml`): pytest + frontend typecheck/unit. It must never
  train — `.pkl` files and MoneyPuck CSVs are gitignored, so CI has neither.
- **Live draft-day mode ships** (`frontend/src/components/rink/DraftBoard.tsx` +
  `src/lib/liveDraft.ts`): mark-drafted toggles, VORP recomputed against the remaining pool,
  positional-run strip, `localStorage` persistence. Verified in the running app — drafting the
  top five centers lifted every remaining center ~14.8 VORP.
- **`main.py mock-draft --year YYYY`** exists and is trustworthy.
- **Keeper identification is solved** (owner's rule, 2026-07-20): *the final 4 picks of every
  team are the kept players*, per team **by pick number**, never by round.

---

## Landmines

**Keeper rounds are not a thing you can infer.** `derive_keepers()` uses pick number because
picks are traded wholesale — in 2025 team t.9 held only rounds 1-9 and t.10 only rounds 10-18.
Six of ten teams *happened* to show a clean one-per-round-15-to-18 pattern, which is exactly the
misleading regularity that makes a round rule look right. It is not.

**Yahoo's `league_ids()` is not scoped by the Game's sport.** `yfa.Game(oauth, 'nhl')` does not
filter the listing call. Asking for 2025 without `game_codes=['nhl']` returns five leagues across
several sports, and the first is fantasy *baseball* — this genuinely happened. Historical league
ids also change yearly (2024: `453.l.27273`, 2025: `465.l.33072`), so the league *name* is the
only stable identifier. `_assert_expected_league` now checks name and team count at fetch time.

**A partial keeper list is worse than none.** `load_season_keepers` requires exactly
`TEAM_COUNT * KEEPER_COUNT` names and refuses anything else, because a 24-of-40 file completes,
looks plausible, and silently leaves 16 keepers draftable — the original bug, again.

**`node --test` glob syntax needs Node 22.** The repo runs Node 20, where a quoted glob fails.
`test:unit` passes a directory instead; don't "fix" it back.

**The held-out look is spent.** There is no second honest test of the draft model. Any change to
it cannot be re-validated this way.

---

## Improving the draft model — what the evidence actually supports

The mock draft is the only product-level evidence, so start from what it does and does not say.

### First, a statistical caveat that limits everything below

**n = 14 picks.** A −1.75% margin on fourteen picks cannot distinguish "a wash" from "a modest
real edge" — it is well inside noise. The honest reading is *no detectable edge*, not *proven
equal*. Any improvement claiming to be validated by a single mock draft is overclaiming.

Consequence: **validation power is itself a work item.** Options, roughly in order of value:

1. Mock-draft additional seasons. Blocked by leakage for 2024 (the model trained on those
   outcomes) — usable only as a harness check, not evidence.
2. Keep **validation Spearman on held-out seasons** as the primary model metric (hundreds of
   players, not fourteen), and treat the mock draft as a sanity check on the *product*, which is
   what `fht-quality-gates` §2 already says.
3. Retrain on an earlier boundary to free a clean season for a second mock draft. Costs model
   quality; probably not worth it.

### A real modelling weakness, independent of this result

**Every skater is projected for exactly 78 games.** `buildFullProjections` sets
`projections['projected_gp'] = 78` flat (main.py), so `projected_total = projected_fpPerGame *
78` and VORP inherits it. Goalies already get a modelled `projected_gp` (`gp_w3` clipped to
`GOALIE_GP_CAP`) precisely because workload *is* their value — skaters get nothing.

This matters because the draft target is deliberately **PPG**, to avoid conflating skill with
injury luck. That is correct. But multiplying by a flat 78 re-introduces the same problem in
reverse: it ranks a 55-game player as though they were a 78-game player.

**Honest caveat: this did not decide the 2025 mock draft.** I checked, expecting it to be the
culprit, and it is not — the board's roster was slightly *healthier* than the owner's (mean 66.8
GP vs 65.2; 4 of 12 skaters under 65 games vs 5 of 12). So this is a principled fix, not a
diagnosed cause. Do not sell it as the reason the board lost.

Implementation sketch: mirror the goalie path — a weighted recent-GP feature (the goalie ranker
uses a 50/30/20 weighting) as `projected_gp` for skaters, clipped sensibly. Gate it on validation
Spearman against the current flat-78 board, not on a re-run mock draft.

### Ideas the data does NOT support — don't chase these

- *"The board over-drafts injury-prone players."* Checked, false (above).
- *"The board over-values goalies."* The board's goalies scored 358.9 (Sorokin, Binnington) vs
  the owner's 394.6 (Shesterkin, Kuemper). A 36-point gap across two picks is noise at n=2.
- *Any story built on a single pick.* The board's worst was Nichushkin over DeBrincat (−131);
  its best was Forsberg over Fox (+96). Both are single draws.

### Where good ideas have actually come from here

Per `fht-research-frontier` methodology (g): reading the model code cold and noticing gaps,
`backtest.KNOWN_PICKUPS` misses, and Learning Log post-mortems — **not** from adding model
complexity. The LSTM is the counterexample and stays parked.

For draft-specific feature ideas, `fht-draft-campaign` owns the roadmap. The frontier skill is
pickup-focused and its items 1-4 are about the pickup/cooling models, not the draft ranker.

---

## Open questions for the owner

**`.claude/skills/OPEN-QUESTIONS.md` #1b — do keepers really cost a fixed round 15-18?**
This affects a *shipped* tool, not just docs. `src/keeper.py` hardcodes
`KEEPER_ROUNDS = (18, 17, 16, 15)` and `round_pick_costs()` prices keepers off those rounds. But
the owner's stated rule is "the final 4 picks," and 2025 has keepers as early as round 10
(Matthews, t.5). If cost is not a fixed round, `net_keeper_value` on the shipped keeper board is
off. **Do not "fix" `KEEPER_ROUNDS` without the owner stating the actual rule** — it is equally
possible the rule changed between seasons or that Yahoo records cost differently from the league.

---

## Next up, unblocked

1. **Keepers → summaries.** When the 2026 keepers are announced: fill `data/raw/keepers.csv` →
   `main.py draft` (the filter applies automatically, `main.py:253`) → generate summaries for the
   top ~200 *of the filtered pool* → re-run `api_export.py`. Owner's decision: do not spend API
   credits on the ~40 players who won't be in the pool. Currently 50 of 774 have summaries.
2. **Resolve OPEN-QUESTIONS #1b** before leaning on keeper recommendations.
3. **Skater `projected_gp`**, if you want a model change with a clear rationale.
4. Deferred from the previous handoff and still deferred: advisor context scaling (fine at 18
   roster players), `reports/metrics.jsonl`, Phase E-ML tuning — all post-draft.

## Don't relitigate

MoneyPuck is the single stats source; no auto-downloader (licensing); one scoring source per
stat type; season-based splits only; draft target is PPG not totals; LSTM stays parked.
Full list with citations in `fht-architecture-contract`.
