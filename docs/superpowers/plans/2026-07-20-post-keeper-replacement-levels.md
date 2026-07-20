# Post-keeper replacement levels

> **SUPERSEDED 2026-07-20 by commit ac6e9b8 — do not execute this plan.**
>
> Its diagnosis is wrong in a way worth keeping on the record. It blames the 0-centers board on
> VORP being computed against a pre-keeper pool, and proposes filtering the pool while leaving
> `REPLACEMENT_RANKS` alone. Simulated on the 2026 board before building it, that fix does not
> change the roster — all three candidate definitions still draft 6 D and 1 C:
>
> | definition | C level | D level | greedy-14 |
> |---|---|---|---|
> | rank 24/48, full pool (then-current) | 234.5 | 150.9 | 6D 4L 2G 1C 1R |
> | same ranks, post-keeper pool (this plan) | 208.3 | 143.4 | 6D 4L 2G 1C 1R |
> | rank − keepers at position, post-keeper pool | 236.0 | 150.9 | 6D 4L 2G 1C 1R |
>
> Two corrections. First, the real defect is the **drafter**, not the replacement level:
> `mockDraft._best_available` capped positions but set no floors, and `grade()` summed all 14
> picks with no lineup-legality check. This plan deferred both as "out of scope — do not bundle,"
> which was backwards. Second, "rank 24 on the post-keeper pool" double-counts the keeper removal;
> replacement level is the marginal *drafted* starter, so the rank has to come down with the
> keepers (`10 × slots − keepers at that position`).
>
> What shipped instead: positional floors, keeper-aware floors AND caps, demand-aware ranks, and
> `lineup_fp` grading. See the July 2026 Learning Log entry in `PROJECT-PLAN.md`.
>
> Kept unedited below because the measurement that refuted it is the useful part of the record.

## Context

VORP is computed against a pool that includes players nobody can draft. `runDraft`
([main.py:278-280](D:/repos/FantasyHockeyTools/main.py)) deliberately computes
`vorp_column` **before** `filterOutKeepers`, on the rationale that "replacement level is about
league-wide talent depth, not about who happens to still be free." In a keeper league that
rationale is wrong, and it breaks the board.

Discovered 2026-07-20 by sweeping the 2025 mock draft across all 10 managers
(`main.py mock-draft --year 2025 --all-teams`). The board lost to 9 of 10, mean −6.48%. Cause:
**the board drafted 0 centers in 140 picks** — 60 D (42.9%), 40 L, 20 G, 20 R, 0 C. Team rosters
like 6D/3L/2G/2R/1R cannot even be legally fielded (`ROSTER_SLOTS` requires 2 C).

Why: every elite center is a keeper (McDavid, MacKinnon, Draisaitl, Matthews, Eichel, Point,
Bedard, Hughes, Stutzle, Celebrini, Marner, Scheifele, Necas, Johnston). C replacement stays
pinned at the 24th-best center *including the kept ones*, so no draftable center ever clears it
and every C carries negative VORP forever. D replacement is drawn 48 deep, where keepers thin the
pool much less.

Measured on the 2024 board with the 40 real 2025 keepers removed:

| pos | pre-keeper | post-keeper | delta |
|---|---|---|---|
| C | 232.4 | 211.7 | −20.6 |
| R | 209.3 | 180.9 | −28.4 |
| G | 186.9 | 167.5 | −19.4 |
| L | 191.1 | 172.3 | −18.8 |
| D | 156.3 | 150.6 | **−5.7** |

D barely moves while everything else drops ~20 — that gap *is* the D inflation. Top-60 position
mix goes from 0 draftable centers to D 19 / R 14 / L 9 / G 9 / **C 9**.

This mispriced the live draft board, not just the backtest. Fixing it is the point.

**Intended outcome:** one definition of VORP across the app — replacement level measured against
the players actually available to draft.

## Design

`keeper.replacement_levels(projections)` stays pure: it computes levels from whatever frame it is
given. `src/keeper.py`'s docstring says the module is "deliberately independent of Yahoo, the
draft model, and the frontend" — preserve that. Callers own the keeper list and decide the pool.

Two different pools, because the two questions differ:

- **Draft board** — pool = everyone minus **all 40** keepers. You cannot draft any of them.
- **Keeper analyzer** — pool = everyone minus **other teams' 36**. Your own roster must stay on
  the board or `analyze_keepers` fuzzy-matching (`keeper.py:144`) reports "No projection match"
  for the very players it is meant to rate.

## Changes

### 1. `src/keeper.py` — optional `pool` argument

- `vorp_column(projections, pool=None)` — levels from `pool` (default `projections`), subtracted
  from `projections`. Lets a caller rank one frame against another frame's replacement levels.
- `analyze_keepers(roster, projections, pool=None)` — pass `pool` to both `replacement_levels`
  **and** `round_pick_costs`; pick cost is what that pick would fetch from the draft pool, so it
  is post-keeper too.
- Leave `replacement_levels` and `REPLACEMENT_RANKS` alone. The ranks encode roster demand
  (2C/2L/2R/4D/2G × 10 teams plus bench) and are unchanged by this fix.
- Keep the existing `len(players) < rank` guard — it is the safety net if a pool is over-filtered.

### 2. `main.py::runDraft` — filter before ranking

Move `keepers.loadKeepers()` / `filterOutKeepers` **above** the `vorp_column` call, then compute
VORP on the filtered frame. No `pool` argument needed here.

The degraded path must survive: when `data/raw/keepers.csv` is missing or empty, the existing
`except (FileNotFoundError, ValueError)` warning still fires and VORP falls back to the full pool
— today's behaviour, which is correct when keepers genuinely aren't announced yet.

**Rewrite the comment at main.py:278-279.** It currently states the bug's rationale as fact; left
in place, a future session will revert this fix. Replace with why post-keeper is correct in a
keeper league, and cite the 0-centers finding.

### 3. `main.py::runKeeper` — build the keeper-analyzer pool

Load `keepers.csv`, subtract the authenticated roster's names (fuzzy, `rapidfuzz` at cutoff 85 as
everywhere else — reuse the pattern in `keepers.filterOutKeepers`), build the pool, pass it to
`analyze_keepers(..., pool=pool)` and through to `keeper_advisor.build_context`.

Same graceful degradation: no keepers.csv → `pool=None` → today's behaviour plus a warning.

### 4. `src/keeper_advisor.py` — thread the pool through

`_board_comparisons(projections, pool=None)` (line 118) and `build_context(..., pool=None)`. The
advisor's `vorp_rank` must agree with the board's, or the chat will contradict the table.

### 5. `main.py::_mockDraftBoard` — same reordering

Compute `vorp_column` **after** `mockDraft.remove_keepers`, and fix the comment there too (it
carries the same wrong rationale).

### 6. `frontend/src/lib/liveDraft.ts` — comment only, no logic change

`replacementLevels` already recomputes against the remaining pool, and `draft_rankings.csv` is
already keeper-filtered before export, so the frontend is correct once the CSV is. **Do not
change the logic.** Update the docstring at lines 6-10, which claims the exported `vorp` is
"computed against the FULL preseason pool" — after this change it is the post-keeper pool.
Leave `REPLACEMENT_RANKS` (line 22) mirroring `keeper.py` as-is.

### 7. `data/raw/keepers.csv` — create it (does not exist)

Seeded from the 2025 draft (derived via `mockDraft.derive_keepers`). `loadKeepers` reads only
`player_name`, so the `team` column is for hand-editing convenience and is ignored.

**These are last season's keepers and will be wrong for the 2026 draft — the owner edits from
here.** Until then `runDraft` output should be treated as provisional.

```csv
player_name,team
Evan Bouchard,1
David Pastrnak,1
Kirill Kaprizov,1
Cale Makar,1
Andrei Vasilevskiy,2
Macklin Celebrini,2
Jack Eichel,2
Nikita Kucherov,2
Mark Scheifele,3
Jason Robertson,3
Zach Werenski,3
Connor McDavid,3
Jake Guentzel,4
Artemi Panarin,4
Quinn Hughes,4
Nathan MacKinnon,4
Connor Bedard,5
Jack Hughes,5
Mikko Rantanen,5
Auston Matthews,5
Juuse Saros,6
Andrei Svechnikov,6
Clayton Keller,6
Leon Draisaitl,6
Jake Oettinger,7
Martin Necas,7
Rasmus Dahlin,7
Kyle Connor,7
Sergei Bobrovsky,8
Matthew Tkachuk,8
William Nylander,8
Brady Tkachuk,8
Jeremy Swayman,9
Matvei Michkov,9
Wyatt Johnston,9
Tim Stutzle,9
Connor Hellebuyck,10
Brayden Point,10
Sam Reinhart,10
Mitch Marner,10
```

Team 9 is the owner's.

## Tests (write first — this is a class (a) change per `fht-quality-gates`)

In `tests/test_keeper.py`:

- `vorp_column` with an explicit `pool` uses the pool's levels, not the ranked frame's.
- `vorp_column` with `pool=None` is byte-identical to today (no silent behaviour change for the
  degraded path).
- **Regression test for the actual bug:** build a board where the top-24 centers are keepers;
  assert C replacement drops and at least one draftable center has positive VORP. Name it after
  the symptom so nobody re-introduces it.
- `analyze_keepers(pool=...)` keeps rating a roster player who is absent from the pool — the
  own-keepers case that would otherwise regress to "No projection match".
- `round_pick_costs` uses the pool.

In `tests/test_mock_draft.py`: the mock board's VORP is computed after keeper removal.

Frontend: no new tests (no logic change), but `npm test` must stay green.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -v          # expect 152+ passed, 0 failed
cd frontend; npm run typecheck; npm test; cd ..
```

End-to-end:

1. `.\.venv\Scripts\python.exe main.py draft` — **eyeball gate:** the top 20 by VORP must now
   contain centers. Zero centers means the fix did not take. Confirm the "removed N of 40
   keepers" line prints.
2. `.\.venv\Scripts\python.exe main.py keeper` — keeper values will move (replacement dropped
   ~20 FP at most positions, so raw keeper value rises). Sanity-check the top 4 are still
   plausible.
3. `.\.venv\Scripts\python.exe api_export.py` then `cd frontend; npm run dev` — board renders,
   VORP column populated, live-draft mode still recomputes on pick.
4. `.\.venv\Scripts\python.exe main.py mock-draft --year 2025 --all-teams` — compare against the
   recorded pre-fix baseline in `reports/mock_draft_2025_all_noinj.json`: board lost 9 of 10,
   mean −6.48%, 0 centers drafted. Expect the position mix to balance and the margin to improve.

   **This is not a fresh held-out confirm.** 2025 was spent as the FINAL GATE and has now been
   looked at repeatedly. Report any new margin as directional evidence about the fix's direction,
   never as proof the board beats hand-drafting.

## Follow-ups (out of scope — do not bundle)

- **Positional minimums in the mock draft.** `MAX_BY_POSITION` (`src/mockDraft.py:64`) caps but
  sets no floors, and `grade()` sums FP with no lineup-legality check, so the board can post a
  total from an unfieldable roster. This fix reduces the symptom but does not remove the hole.
- **`fht-architecture-contract` / `CLAUDE.md`** — record that replacement level is post-keeper,
  superseding the old "league-wide talent depth" decision, so it is not relitigated.
- **PROJECT-PLAN Learning Log** — record the 10-team sweep and the 0-centers root cause.
