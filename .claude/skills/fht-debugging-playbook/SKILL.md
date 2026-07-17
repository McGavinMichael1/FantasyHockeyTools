---
name: fht-debugging-playbook
description: Use when a test fails, a FileNotFoundError appears for a model or MoneyPuck CSV, pickup/draft output looks stale or unchanged after a code or data change, an aggregation shows doubled stats, fuzzy name matching drops a player, the NHL API hangs or 429s, Yahoo OAuth errors appear, or a model's AUC looks suspiciously good. Not for routine operation or fix validation.
---

# FHT debugging playbook

Symptom-to-cause triage for this solo fantasy-hockey ML repo, plus an archaeology appendix of
settled incidents. Read the lead item first — it is an open, verified regression, not history.

## 1. Lead item — LIVE test failure (verified 2026-07-05, OPEN)

```
.\.venv\Scripts\python.exe -m pytest -v
```
Actual result: **1 failed, 4 passed in 0.57s.**
`FAILED tests/test_moneypuck.py::test_load_game_logs_filters_season_and_keeps_situations`

Traceback bottom line:
```
src\moneypuck.py:76: FileNotFoundError: Missing required MoneyPuck data files: ...
```

**Mechanism** (read `src/moneypuck.py:49-93` and `tests/test_moneypuck.py:20-48` yourself):
`loadGameLogs()` checks `os.path.exists(history_file)` / `current_file` and raises
`FileNotFoundError` at line 76 — *before* the cache-hit branch at lines 80-83
(`if os.path.exists(cache_file): ... return pd.read_csv(cache_file)`). The test's second call
deletes `history_file`/`current_file` and touches `cache_file` to prove the cache is served
without re-reading sources — exactly what the docstring promises: "the cache is reused until
the current-season file is replaced with a newer download" (`src/moneypuck.py:53-54`). With the
guard ahead of the cache check, any cache hit where a source happens to be missing now raises
instead of returning cached data — not hypothetical here: `moneypuck_games_2020.csv` (Jul 3) is
already newer than `moneypuck_current.csv` (Apr 3), i.e. living in the branch this test covers.

**Root cause history**: `bb9bf9d` (PR #1, 2026-07-04, "feat: Next.js frontend dashboard for
pickup/cooling visualization (#1)") bundled "Add helpful error messages for missing MoneyPuck
files" as one bullet among unrelated changes (frontend, cache TTL, Yahoo optional). That bullet
is the regression — the new existence guard landed ahead of the pre-existing cache logic.
`baa1ab1` (PR #2, 2026-07-05) merged on top without re-running pytest, verified by the failure
being reachable from a clean `main` checkout with no working-tree changes.

**Fix options (analysis only — this skill does not modify `src/moneypuck.py`)**:
1. Move the missing-file guard to after the cache-hit check, so it fires only on an actual
   cache-miss path that then needs to read sources.
2. Make the guard conditional on cache absence/staleness — skip it whenever the existing
   `os.path.exists(cache_file)` branch would already serve a fresh read.
Both preserve the friendlier error message; both restore the cache-first contract.

**The decision that matters**: the test is not wrong. It pins the documented, intentional
"offline cache" behavior — you can develop against `moneypuck_games_2020.csv` with neither raw
CSV present. Treat "the test must be stale" as a hypothesis to check against the docstring and
Archaeology row 6, not a conclusion (see Traps, item 1). Route any actual fix through
`fht-quality-gates`.

## 2. Symptom → triage table

| Symptom | Likely cause | Discriminating check | Fix / reference |
|---|---|---|---|
| `FileNotFoundError` on `models/pickups/model.pkl` (or `models/draft/model.pkl`) | Model binaries are gitignored (`.gitignore:39` `models/**/*.pkl`, "retrain locally"); only `.gitkeep` ships (verified, no `.pkl` on disk) | `find models -type f` shows only `.gitkeep` | `.\.venv\Scripts\python.exe main.py train-pickups` (writes `model.pkl` + `reports/pickup_*.png`, several minutes, RandomizedSearchCV) |
| `FileNotFoundError` on a MoneyPuck CSV (`2008_to_2024.csv` / `moneypuck_current.csv`) | No auto-downloader by design (`src/moneypuck.py:1-6`, license notice); files are gitignored, hand-download only | Error message lists both required paths and the moneypuck.com/data.htm URL (`src/moneypuck.py:69-74`) | Manual download runbook lives in `fht-operations`, not here |
| `checkCurrentFreshness()` prints "moneypuck_current.csv is N days old" | `STALE_DAYS = 3` (`src/moneypuck.py:22,42`) vs. file mtime | Verified today: prints "...is 93 days old..." returns `False` | Expected in the current offseason (season over; next DL ~October). Once in-season, the same message is a real "you're missing pickups" signal |
| Pickup/draft output looks stale after a data or feature-code change | 24h caches: `players_cache.csv` (`src/dataProcessing.py:56-63` `getWithCache` — the only remaining 24h NHL cache in the pickup path) and `current_players_features.csv` (`main.py:34-45` `latestGameState`, same rule) | Compare mtimes (below); a cache under 24h wins regardless of what changed | Delete the specific CSV to force a refetch/rebuild; no `--no-cache` flag exists |
| Changed feature code but numbers didn't move | `current_players_features.csv` or `moneypuck_games_{min_season}.csv` is still "fresh" by mtime and gets read instead of recomputed | Cache reused whenever `os.path.getmtime(cache_file) > os.path.getmtime(current_file)` (`src/moneypuck.py:80-83`) — code changes never invalidate it | Delete the cache after any change to `mlFeatures.py`/`fantasyPoints.py`/`moneypuck.py` aggregation logic |
| Rebuilding `moneypuck_games_2020.csv` takes minutes, reads the full 2.6 GB file | Expected — `pd.read_csv(history_file, usecols=GAME_COLUMNS)` over `2008_to_2024.csv` (2,620,103,561 bytes, verified) | Watch for "Loading MoneyPuck data from..." / "Cached to..." prints (`src/moneypuck.py:85,92`) | Not a bug; don't kill it early |
| "No good match found for `<player>`" (or a silent pool miss) | `rapidfuzz.process.extractOne(..., score_cutoff=85)` (`src/yahooAPI.py:31`, `src/keepers.py`) misses accents, nicknames, Jr./Sr. | Diff the Yahoo/keepers name string against MoneyPuck's `name` column | Worst case is silent — no error, player just stays in/out of the pool. Check variants by hand; no fallback matcher |
| NHL API calls hang or run slowly | 429 retry loops: `src/nhlAPI.py` sleeps 5s (roster), 15s (player landing), verified lines ~11-13, ~39-41 | `grep -n "429\|sleep" src/nhlAPI.py` | Expected cold-cache load: ~834 players × 2 stat fetches + 32 roster calls ≈ **1,700-1,800 requests** (UNVERIFIED estimate from row counts, not a timed run — hits live network) |
| Yahoo OAuth errors during `main.py pickups` | `main.py:82-92`: missing `oauth2.json` → `FileNotFoundError` caught with a setup hint; other auth failures caught broadly and printed | Both branches print and continue; `rostered_nhle_ids` stays empty | Intentional graceful degradation. For real expiry, delete cached token state, re-auth per `YAHOO_SETUP.md`; never print `.env`/`oauth2.json` contents |
| `UnboundLocalError` on a variable named `time` | Local variable shadows `import time` | Look for `time = ...` below `import time` in the same scope | Rename it — repeat of the March 2026 lesson (`PROJECT-PLAN.md` Learning Log); it has recurred before |
| pandas misparses hand-edited `data/raw/keepers.csv` | Trailing comma on one row shifts columns | `src/keepers.py:27-30` comment; guarded by `pd.read_csv(path, index_col=False)` | If it recurs, the guard was removed or the malformation differs — inspect the raw CSV, don't blindly re-add the flag |
| Every stat roughly doubled after an aggregation | Summed raw per-situation rows (`all`, `5on4`, `4on5`...) instead of `fantasyPoints.moneypuckGamePoints`'s collapsed `'all'` row, which already totals them | `src/moneypuck.py:95-102` docstring; `buildPlayerSeasons` calls `moneypuckGamePoints` first (`:104`) to avoid this | Never `groupby(...).sum()` directly over `loadGameLogs()` output |
| Model's validation AUC looks suspiciously high | Leakage: random split, a forward-looking feature missing `shift(1)`, label leaking into features, or the test season touched repeatedly | Split by season (train ≤2022, val 2023)? `shift(1)` before `.expanding().mean()` in every rolling feature? `next_5_avg` from future games only? 2024 touched only at the final check? | Compare against the pinned numbers in `fht-quality-gates`' golden inventory (pickup val ≈0.73, cooling ≈0.64, 2026-07-03 retrain). Meaningfully higher on the same split is a leakage signal, not a win |

## 3. Discriminating experiments (read-only, copy-pasteable)

Run just the one failing test file (fast, isolates the regression from the 4 passing tests):
```
.\.venv\Scripts\python.exe -m pytest -v tests\test_moneypuck.py
```

Import-only smoke test (catches signature rot / import-time errors cheaply; pulls in torch, so
first run is slow — verified to exit 0 with no output):
```
.\.venv\Scripts\python.exe -c "import main"
```

Cache vs. source mtime check (verified output below — this is the same cache-hit branch the
failing test's second call exercises):
```powershell
Get-Item data\processed\moneypuck_games_2020.csv, data\raw\moneypuck_current.csv |
    Select-Object Name, LastWriteTime
```
Verified today:
```
Name                     LastWriteTime
----                     -------------
moneypuck_games_2020.csv 2026-07-03 5:28:04 PM
moneypuck_current.csv    2026-04-03 3:27:33 PM
```

Print the canonical scoring weights (confirms nobody introduced a second, drifted copy);
diff the output against the scoring table in `fht-domain-reference` §1 — that table is the
one home for the weight values, not this file:
```
.\.venv\Scripts\python.exe -c "from src import fantasyPoints; print(fantasyPoints.SKATER_WEIGHTS)"
```

Freshness check (verified output shown — 93 days old as of 2026-07-05, expected in the
offseason, see triage table):
```
.\.venv\Scripts\python.exe -c "from src import moneypuck; print(moneypuck.checkCurrentFreshness())"
```

Score one known player-season through `moneypuckGamePoints` and compare to the recorded
acceptance numbers (`PROJECT-PLAN.md` Learning Log / Design Decision A2): 2023-24 Auston
Matthews should total 69G/38A exactly; 2023-24 Connor McDavid 32G/100A exactly, PPP at 42 vs.
official 44 (documented 5-on-3 undercount). Requires loading `data/raw/2008_to_2024.csv`
(2.6 GB) via `loadGameLogs`/`buildPlayerSeasons` — minutes on a cold cache, seconds warm.
UNVERIFIED — not run here (heavy read of the full history file, out of scope for this
file-only task); reproduce by filtering `buildPlayerSeasons` output to McDavid/Matthews
`playerId`.

## 4. Archaeology appendix

| # | Incident | Symptom | Root cause | Evidence | Status |
|---|---|---|---|---|---|
| 1 | ML label ≠ league scoring | Models trained for months on the wrong target | Label used raw G/A/SOG only, not full weighted scoring | `83e9fc1` (canonical scoring), `2c23433` (moneypuck.py owns IO); pinned by `tests/` today | SETTLED |
| 2 | Plot collision destroyed old pickup AUC record | `roc_curve.png` labeled "Pickup Model AUC 0.64" was actually the cooling curve — same filename, overwritten | `94c59ce` gives each model its own `reports/{pickup,cooling}_*.png`; old pickup AUC is unrecoverable per Learning Log | SETTLED — metrics belong in diffable text, not overwritable images |
| 3 | `requirements.txt` drift, streamlit never installed | UI skeleton (`ui/app.py`) had never actually run against its own venv | Fixed by freezing from the working venv, `94c59ce` | SETTLED |
| 4 | LSTM `save()` signature rot | `save(model)` call crashed after the signature changed to `save(model, hidden_size, num_layers)` | One-line fix in `8ac3e09` while parking the model; `lstmPickups.py` header confirms PARKED July 2026 | SETTLED / PARKED — do not un-park before the October draft; `lstmFeatures.py` header notes it still scores G/A/SOG only, not `SKATER_WEIGHTS` |
| 5 | Plan-doc drift, three phases behind code | `PROJECT-PLAN.md` "Current Phase" stale | Learning Log "July 2026": "update Current Phase every session" | SETTLED as process fix; ASSUMED as standing rule per `OPEN-QUESTIONS.md` #2 |
| 6 | Cache-guard regression (lead item) | Test fails on `main` | `bb9bf9d`'s guard runs before the cache-hit check (`src/moneypuck.py:57-76` vs. `80-83`) | Verified 2026-07-05: `1 failed, 4 passed` | **OPEN** |
| 7 | March 2026 micro-lessons | Various | 429 retry sleeps (`src/nhlAPI.py`); mtime age = `time.time() - mtime`, not reversed; `.venv/` vs `venv/` distinct `.gitignore` entries; `to_csv()` returns `None`, don't chain on it | `PROJECT-PLAN.md` Learning Log, "March 2026" | SETTLED, but a checklist worth rechecking (shadowing `time` already recurred once) |

## 5. Traps / red flags — stop and think before you act

- **"The test is wrong, I'll update it."** Check this archaeology table and the docstring
  first. Incident 6 is exactly this trap: the test encodes an intentional offline-cache
  contract; changing it blesses the regression instead of fixing it.
- **"I'll just sum the MoneyPuck rows."** Game logs have one row per player-game *per
  situation* (`all`, `5on4`, `4on5`...); the `'all'` row already totals the rest. Always go
  through `fantasyPoints.moneypuckGamePoints` first.
- **"Results are identical, so my change is a no-op."** Check cache mtimes first —
  `moneypuck_games_2020.csv`, `current_players_features.csv`, and `players_cache.csv` can
  all silently serve pre-change data for up to 24h (or indefinitely, until a newer
  `current_file` download).
- **"AUC went up, ship it."** The gate is baselines plus the backtest (`src/backtest.py`), not
  raw AUC. A higher number on the same season split is more often a bug than a win.
- **"Let me add an auto-downloader for MoneyPuck."** Never — a deliberate, documented license
  decision (`src/moneypuck.py:1-6`), not an oversight to fix.

## When NOT to use this skill

- Running the pipeline day-to-day, refreshing MoneyPuck/NHL/Yahoo data, or understanding caches
  when nothing is actually broken → `fht-operations`.
- Deciding what tests/checks a fix needs before it counts as done, or gating the lead-item fix
  once someone attempts it → `fht-quality-gates`.
- Module boundaries, settled architecture decisions, or "where should this logic live" →
  `fht-architecture-contract`.
- Hockey/scoring/MoneyPuck domain semantics (what a situation column means, league rules) →
  `fht-domain-reference`.
- Executing Phase B/C roadmap work (draft ranker, keeper analyzer) → `fht-draft-campaign`.
- Ideas for improving model performance (features, tuning, architecture) →
  `fht-research-frontier`.

## Provenance and maintenance

- Re-run the lead item's status check any time: `.\.venv\Scripts\python.exe -m pytest -v`.
  As of 2026-07-05 it reports `1 failed, 4 passed in 0.57s` with the failure named above. If it
  instead reports `5 passed`, the regression has been fixed — find the fixing commit with
  `git log --oneline -- src/moneypuck.py` and move Archaeology row 6 to SETTLED with that hash,
  then check whether the fix moved the guard (option 1) or made it conditional (option 2).
- Confirm the introducing/merging commits haven't been rewritten: `git log --oneline -5` should
  still show `baa1ab1` on top of `bb9bf9d`; `git show --stat bb9bf9d` should still list
  `src/moneypuck.py` and the "Add helpful error messages for missing MoneyPuck files" bullet in
  its body.
- Re-verify `SKATER_WEIGHTS` hasn't drifted: rerun the print command in section 3 and diff
  against the scoring table in `fht-domain-reference` §1.
- Re-check cache state before trusting the mtime example: rerun the `Get-Item` one-liner in
  section 3; dates will have moved on by the time this is read.
- If new recurring bug classes show up (a second shadowing incident, a second plot collision,
  etc.), add a row to the archaeology table rather than a new one-off note — the point of this
  file is that nobody re-fights a settled battle from scratch.
