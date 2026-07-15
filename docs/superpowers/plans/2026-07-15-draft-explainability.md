# Draft Explainability + Confidence + Claude Summaries — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-player deterministic explanation (top SHAP factors), a data-driven confidence score, and a batch-generated 1–2 sentence Claude summary to the draft rankings, surfaced via an expandable row in The Rink's Draft board.

**Architecture:** Two pure functions (`compute_confidence`, `top_factors`) live in a new `src/draft_explain.py` and are pytested. A thin booster wrapper (`shap_contributions`) lives in `src/models/draft.py` (model IO, not unit-tested). `main.runDraft` computes both and writes `confidence` + 6 `factor_*` columns into `draft_rankings.csv`. A new resumable script `scripts/build_draft_summaries.py` (the canonical producer) writes `data/processed/draft_summaries.json` keyed by playerId. `api_export.build_draft_list` merges that JSON and passes `confidence`/`factors`/`summary` through. `DraftBoard.tsx` gains a compact confidence column and an expandable detail row (summary text + confidence meter + ± factor list).

**Tech Stack:** Python 3.12, pandas, xgboost (native booster `pred_contribs`), the `anthropic` SDK (new dependency) with the server-side `web_search_20260209` tool, pytest; Next.js/React + CSS modules for the frontend.

## Global Constraints

- Always invoke the venv interpreter explicitly: `.\.venv\Scripts\python.exe` (system `python` may be wrong on Windows).
- pytest config is `pytest.ini` (`pythonpath = .`, `testpaths = ["tests"]`, `test_*.py`). Tests go in `tests/`, follow `tests/test_fantasyPoints.py` style with **hand-computed expected values in a comment above the assertion**.
- pytest is for **pure functions only** — no tests for API wrappers or the summary script (repo doctrine, `fht-quality-gates` §4).
- `CURRENT_SEASON = 2025` (MoneyPuck convention: 2025 = the 2025-26 season). Already defined in `main.py` and `api_export.py`.
- Claude model id is exactly `claude-opus-4-8`. Web-search tool is `web_search_20260209` (name `web_search`) with `max_uses: 3`. Thinking is `{"type": "adaptive"}` (never `budget_tokens` — it 400s on Opus 4.8). API key from `ANTHROPIC_API_KEY`; fail fast if unset. These are copied verbatim from the design spec.
- `draft_summaries.json` schema is the contract: `{playerId: {"summary": str, "generated_at": iso8601, "model": str}}`, playerId as a **string** key.
- Dependency gate (`fht-quality-gates` §1(f)): install `anthropic` into `.venv`, freeze the pin in **both** `pyproject.toml` and `requirements.txt` in the same change, and verify `.\.venv\Scripts\python.exe -c "import main"` still succeeds before committing.
- `data/` is gitignored wholesale, so `draft_summaries.json` (under `data/processed/`) is already ignored — do not commit it, and do not commit `models/**/*.pkl`.
- Summaries are **display-only**: they never feed back into rankings or the model. Confidence is computed in Python, never LLM-assigned.
- Stay on the current branch `feat/draft-explainability`.

---

### Task 1: `src/draft_explain.py` — pure confidence + factor functions

**Files:**
- Create: `src/draft_explain.py`
- Test: `tests/test_draft_explain.py`

**Interfaces:**
- Produces:
  - `FEATURE_LABELS: dict[str, str]` — raw draft-feature column → human label.
  - `feature_label(col: str) -> str` — label for one feature column; `pos_C` → `"Position: C"`; unknown → the column name unchanged.
  - `top_factors(contribs: Mapping[str, float], top_n: int = 3) -> list[dict]` — returns up to `top_n` positive contributions (sorted descending) followed by up to `top_n` negative contributions (sorted ascending / most-negative first), each `{"label": str, "value": float}`. Zero contributions are dropped. Labels come from `feature_label`.
  - `compute_confidence(seasons_of_history: int, feature_gp: int, age: float | None, projection: float, fp_w3: float | None) -> int` — transparent 0–100 score from data depth + stability. `age`/`fp_w3` may be `NaN`/`None` → neutral 0.5 sub-score.

- [ ] **Step 1: Write the failing test**

Create `tests/test_draft_explain.py`:

```python
import math

from src import draft_explain


def test_feature_label_known_position_and_unknown():
    assert draft_explain.feature_label('fpPerGame') == 'Last-season FP/game'
    # pos_* one-hots become a readable position line
    assert draft_explain.feature_label('pos_C') == 'Position: C'
    # an unmapped column falls back to itself, never raises
    assert draft_explain.feature_label('mystery_col') == 'mystery_col'


def test_top_factors_keeps_top_positive_then_negative():
    contribs = {
        'fpPerGame': 0.5,
        'fp_w3': 0.2,
        'PP_share': 0.05,
        'age_at_season_start': -0.3,
        'xGoalsSurplus': -0.1,
        'career_games': -0.4,
        'pos_C': 0.0,  # zero contribution is dropped entirely
    }
    # top 2 positives desc: fpPerGame 0.5, fp_w3 0.2
    # top 2 negatives asc (most negative first): career_games -0.4, age -0.3
    result = draft_explain.top_factors(contribs, top_n=2)
    assert result == [
        {'label': 'Last-season FP/game', 'value': 0.5},
        {'label': '3-season weighted FP/game', 'value': 0.2},
        {'label': 'Career games played', 'value': -0.4},
        {'label': 'Age', 'value': -0.3},
    ]


def test_compute_confidence_full_data_full_score():
    # deep history (>=4 seasons -> 1.0), full season GP (>=70 -> 1.0),
    # peak age 25 -> 1.0, projection == fp_w3 -> stability 1.0
    # 0.25*1 + 0.30*1 + 0.20*1 + 0.25*1 = 1.0 -> 100
    assert draft_explain.compute_confidence(
        seasons_of_history=5, feature_gp=82, age=25.0,
        projection=3.0, fp_w3=3.0) == 100


def test_compute_confidence_thin_data_and_deviation():
    # seasons 2 -> 2/4 = 0.5; gp 35 -> 35/70 = 0.5;
    # age 20 -> max(0.4, 1 - 0.06*3) = 0.82;
    # |2.0 - 3.5| = 1.5 -> stability = 1 - 1.5/2 = 0.25
    # 0.25*0.5 + 0.30*0.5 + 0.20*0.82 + 0.25*0.25
    # = 0.125 + 0.15 + 0.164 + 0.0625 = 0.5015 -> round -> 50
    assert draft_explain.compute_confidence(
        seasons_of_history=2, feature_gp=35, age=20.0,
        projection=2.0, fp_w3=3.5) == 50


def test_compute_confidence_missing_age_and_fp_w3_are_neutral():
    # seasons 4 -> 1.0; gp 70 -> 1.0; age NaN -> 0.5; fp_w3 NaN -> stability 0.5
    # 0.25*1 + 0.30*1 + 0.20*0.5 + 0.25*0.5 = 0.25 + 0.30 + 0.10 + 0.125 = 0.775 -> 78
    assert draft_explain.compute_confidence(
        seasons_of_history=4, feature_gp=70, age=math.nan,
        projection=3.0, fp_w3=math.nan) == 78
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_draft_explain.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.draft_explain'`.

- [ ] **Step 3: Write the implementation**

Create `src/draft_explain.py`:

```python
"""Deterministic draft-ranking explanation: human-readable SHAP factor names
and a transparent data-driven confidence score.

Both public functions are pure (no model, no IO) so they carry pytest coverage
per the repo testing doctrine (fht-quality-gates). The XGBoost booster wrapper
that produces raw SHAP contributions lives in src/models/draft.py; this module
only names and ranks them and computes confidence.

Confidence (0-100) is a documented weighted average of four sub-scores, each in
[0, 1]:
  - history   (0.25): seasons of prior history (saturates at 4 seasons)
  - games     (0.30): games played in the feature season (saturates at 70)
  - age       (0.20): peak-age band 23-28 is most reliable; decays outside
  - stability (0.25): small |projection - fp_w3| = model in line with history
Missing age or fp_w3 contribute a neutral 0.5 rather than penalizing.
"""

import math
from collections.abc import Mapping

# Raw draft-feature column -> human-readable label. Keys mirror
# src/models/draft.BASE_FEATURE_COLS. pos_* one-hots are handled by feature_label.
FEATURE_LABELS = {
    'fpPerGame': 'Last-season FP/game',
    'fp_delta': 'FP/game trend (season-over-season)',
    'fp_w3': '3-season weighted FP/game',
    'PP_share': 'Power-play share of value',
    'hitblock_share': 'Hits + blocks share of value',
    'xGoalsSurplus': 'Shooting luck (goals vs expected)',
    'avgIcetime': 'Average ice time',
    'career_games': 'Career games played',
    'age_at_season_start': 'Age',
    'highDangerShare': 'High-danger shot share',
    'avgGameScore': 'Average game score',
}

# Confidence sub-score weights (documented; sum to 1.0).
_W_HISTORY = 0.25
_W_GAMES = 0.30
_W_AGE = 0.20
_W_STABILITY = 0.25

_HISTORY_FULL_SEASONS = 4.0   # >= 4 prior seasons -> full history score
_GAMES_FULL = 70.0            # >= 70 GP -> full games score
_AGE_PEAK_LO, _AGE_PEAK_HI = 23.0, 28.0
_AGE_DECAY_PER_YEAR = 0.06    # confidence lost per year outside the peak band
_AGE_FLOOR = 0.4
_STABILITY_SCALE = 2.0        # FP/game deviation that drives stability to 0


def feature_label(col: str) -> str:
    """Human-readable name for a draft feature column."""
    if col in FEATURE_LABELS:
        return FEATURE_LABELS[col]
    if col.startswith('pos_'):
        return f"Position: {col[len('pos_'):]}"
    return col


def top_factors(contribs: Mapping[str, float], top_n: int = 3) -> list[dict]:
    """Top `top_n` positive then top `top_n` negative SHAP contributions.

    Positives sorted descending (biggest push up first); negatives sorted
    ascending (biggest push down first). Zero contributions are dropped.
    Returns a flat list of {"label", "value"}; the sign of value encodes
    direction, so consumers colour by sign.
    """
    items = [(feature_label(k), float(v)) for k, v in contribs.items()]
    positives = sorted((it for it in items if it[1] > 0),
                       key=lambda it: it[1], reverse=True)[:top_n]
    negatives = sorted((it for it in items if it[1] < 0),
                       key=lambda it: it[1])[:top_n]
    return [{'label': label, 'value': value} for label, value in positives + negatives]


def _is_missing(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def _age_score(age) -> float:
    if _is_missing(age):
        return 0.5
    if _AGE_PEAK_LO <= age <= _AGE_PEAK_HI:
        return 1.0
    gap = (_AGE_PEAK_LO - age) if age < _AGE_PEAK_LO else (age - _AGE_PEAK_HI)
    return max(_AGE_FLOOR, 1.0 - _AGE_DECAY_PER_YEAR * gap)


def _stability_score(projection, fp_w3) -> float:
    if _is_missing(fp_w3):
        return 0.5
    deviation = abs(float(projection) - float(fp_w3))
    return max(0.0, 1.0 - deviation / _STABILITY_SCALE)


def compute_confidence(seasons_of_history: int, feature_gp: int, age,
                       projection: float, fp_w3) -> int:
    """Transparent 0-100 confidence from data depth + projection stability."""
    history_score = min(max(seasons_of_history, 0) / _HISTORY_FULL_SEASONS, 1.0)
    games_score = min(max(feature_gp, 0) / _GAMES_FULL, 1.0)
    age_score = _age_score(age)
    stability_score = _stability_score(projection, fp_w3)
    score = (_W_HISTORY * history_score
             + _W_GAMES * games_score
             + _W_AGE * age_score
             + _W_STABILITY * stability_score)
    return int(round(100 * score))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_draft_explain.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/draft_explain.py tests/test_draft_explain.py
git commit -m "feat(draft): confidence + SHAP-factor naming pure functions

```

---

### Task 2: `shap_contributions` booster wrapper in `src/models/draft.py`

**Files:**
- Modify: `src/models/draft.py` (add one function after `predict`)

**Interfaces:**
- Consumes: the saved payload `{'model': XGBRegressor, 'feature_cols': list}` from `load()`, and `_feature_matrix` (already in the module).
- Produces: `shap_contributions(df: pd.DataFrame) -> pd.DataFrame` — one row per input row (same index as `df`), one column per feature in `feature_cols`, each cell the feature's additive contribution to that row's prediction. The XGBoost bias/base column is dropped.

Model IO — not unit-tested (repo doctrine). Verified end-to-end in Task 3.

- [ ] **Step 1: Add the function**

In `src/models/draft.py`, insert after the `predict` function (before `def load():`):

```python
def shap_contributions(df: pd.DataFrame) -> pd.DataFrame:
    """Per-row SHAP feature contributions from the trained XGBoost booster.

    Uses the booster's native `pred_contribs=True` (no new dependency). Returns
    a DataFrame indexed like `df`, one column per feature in the saved
    `feature_cols`. The final column returned by XGBoost is the bias/base value
    and is dropped. Consumed by main.runDraft to explain each ranking.
    """
    payload = load()
    X = _feature_matrix(df, payload['feature_cols'])
    booster = payload['model'].get_booster()
    contribs = booster.predict(xgb.DMatrix(X), pred_contribs=True)
    return pd.DataFrame(contribs[:, :-1], index=df.index,
                        columns=payload['feature_cols'])
```

`xgb` and `pd` are already imported at the top of the module.

- [ ] **Step 2: Smoke-check the wrapper against the trained model**

Run (the model and `player_seasons.csv` already exist locally):

```bash
.\.venv\Scripts\python.exe -c "import pandas as pd; from src.features import draft as d; from src.models import draft as m; df=d.build_draft_features(pd.read_csv('data/processed/player_seasons.csv')); cur=df[df['season']==2025].head(3); c=m.shap_contributions(cur); print(c.shape); print(list(c.columns)); print(c.iloc[0].sort_values())"
```

Expected: prints a `(3, N)` shape where N == number of feature columns (11 base + the `pos_*` one-hots), the column list matches `BASE_FEATURE_COLS` + `pos_*`, and a sorted Series of signed contributions for the first player. No exception.

- [ ] **Step 3: Commit**

```bash
git add src/models/draft.py
git commit -m "feat(draft): expose per-player SHAP contributions from the booster

```

---

### Task 3: Wire confidence + factors into `main.runDraft`

**Files:**
- Modify: `main.py` (`runDraft`, plus two imports)

**Interfaces:**
- Consumes: `draft_explain.compute_confidence`, `draft_explain.top_factors` (Task 1); `draftModel.shap_contributions` (Task 2).
- Produces: `data/processed/draft_rankings.csv` gains a `confidence` column (int) and six factor columns `factor_1`..`factor_6`. Columns 1–3 hold the top positive factors, 4–6 the top negative, each a JSON string `{"label": str, "value": float}`; unused slots are the empty string. These are the "6 SHAP factor columns" the design references.

- [ ] **Step 1: Add imports**

In `main.py`, the top imports currently include `import argparse` / `import os` and `from src import ...`. Add `import json` after `import argparse` (line 1) and add `from src import draft_explain` alongside the other `from src import` lines:

```python
import argparse
import json
import os
```

and, in the `from src import ...` block (near `from src import backtest`):

```python
from src import draft_explain
```

- [ ] **Step 2: Compute explanations inside `runDraft`**

In `main.py`, find in `runDraft`:

```python
    current = current[current['gamesPlayed'] >= 20]
    current['projected_fpPerGame'] = draftModel.predict(current)

    rankings = current[['playerId', 'full_name', 'position', 'gamesPlayed',
                        'fpPerGame', 'projected_fpPerGame']].copy()
    # age at the UPCOMING season start (draft-day age), one year past the
    # feature season's age_at_season_start
    rankings['age'] = current['age_at_season_start'] + 1
    rankings['projected_total'] = rankings['projected_fpPerGame'] * 78
    rankings['delta_vs_last'] = rankings['projected_fpPerGame'] - rankings['fpPerGame']
```

Replace it with (adds explanation columns, index-aligned to `current`, before any sort/keeper filter):

```python
    current = current[current['gamesPlayed'] >= 20]
    current['projected_fpPerGame'] = draftModel.predict(current)

    rankings = current[['playerId', 'full_name', 'position', 'gamesPlayed',
                        'fpPerGame', 'projected_fpPerGame']].copy()
    # age at the UPCOMING season start (draft-day age), one year past the
    # feature season's age_at_season_start
    rankings['age'] = current['age_at_season_start'] + 1
    rankings['projected_total'] = rankings['projected_fpPerGame'] * 78
    rankings['delta_vs_last'] = rankings['projected_fpPerGame'] - rankings['fpPerGame']

    # --- Explainability: data-driven confidence + top SHAP factors ---
    # Seasons of prior history feeds confidence: count the distinct seasons each
    # player appears in, up to and including the feature season.
    seasons_of_history = (df[df['season'] <= CURRENT_SEASON]
                          .groupby('playerId')['season'].nunique())
    rankings['confidence'] = [
        draft_explain.compute_confidence(
            seasons_of_history=int(seasons_of_history.get(pid, 1)),
            feature_gp=int(gp),
            age=age,
            projection=float(proj),
            fp_w3=fp_w3,
        )
        for pid, gp, age, proj, fp_w3 in zip(
            current['playerId'], current['gamesPlayed'], rankings['age'],
            current['projected_fpPerGame'], current['fp_w3'])
    ]

    # Six factor columns: top 3 positive then top 3 negative SHAP contributions,
    # each a JSON {"label", "value"} cell (empty string when a slot is unused).
    contribs = draftModel.shap_contributions(current)
    factor_cols = [f'factor_{i}' for i in range(1, 7)]
    factor_rows = []
    for idx in current.index:
        factors = draft_explain.top_factors(contribs.loc[idx].to_dict(), top_n=3)
        cells = [json.dumps({'label': f['label'], 'value': round(f['value'], 4)})
                 for f in factors]
        cells += [''] * (len(factor_cols) - len(cells))
        factor_rows.append(cells[:len(factor_cols)])
    for col, values in zip(factor_cols, zip(*factor_rows)):
        rankings[col] = list(values)
```

- [ ] **Step 3: Show confidence in the printed top-20 (eyeball gate)**

In `runDraft`, find the final print block:

```python
    print("\n=== Top 20 projected for next season (FP/game) ===")
    print(rankings[['full_name', 'position', 'age', 'gamesPlayed',
                    'fpPerGame', 'projected_fpPerGame', 'projected_total', 'delta_vs_last']]
          .head(20)
          .to_string(index=False))
```

Add `'confidence'` to the displayed columns:

```python
    print("\n=== Top 20 projected for next season (FP/game) ===")
    print(rankings[['full_name', 'position', 'age', 'gamesPlayed',
                    'fpPerGame', 'projected_fpPerGame', 'projected_total',
                    'delta_vs_last', 'confidence']]
          .head(20)
          .to_string(index=False))
```

- [ ] **Step 4: Run it end to end and verify the CSV**

```bash
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe main.py draft
```

Expected: prints the top-20 table now including a `confidence` column, and "Wrote N players to data/processed/draft_rankings.csv". Then verify the new columns exist and parse:

```bash
.\.venv\Scripts\python.exe -c "import pandas as pd, json; df=pd.read_csv('data/processed/draft_rankings.csv'); assert 'confidence' in df.columns; assert all(f'factor_{i}' in df.columns for i in range(1,7)); r=df.iloc[0]; print(int(r['confidence'])); print(json.loads(r['factor_1'])); print(json.loads(r['factor_4']))"
```

Expected: an int in 0–100, then two `{"label": ..., "value": ...}` dicts (factor_1 positive value, factor_4 negative value). No exception. **Eyeball gate:** the top-20 should still be elite skaters — the confidence column must not have reordered anything (rankings still sort by `projected_fpPerGame`).

- [ ] **Step 5: Confirm the pure-function tests and import still pass**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_draft_explain.py -v
.\.venv\Scripts\python.exe -c "import main"
```

Expected: tests PASS; `import main` exits 0.

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "feat(draft): write confidence + 6 SHAP factor columns to draft_rankings.csv

```

---

### Task 4: Merge summaries + explanations in `api_export.build_draft_list`

**Files:**
- Modify: `api_export.py` (`build_draft_list`, add `SUMMARIES_PATH` + two helpers)

**Interfaces:**
- Consumes: `data/processed/draft_rankings.csv` with the columns from Task 3, and optional `data/processed/draft_summaries.json` (Task 5 / manual producer).
- Produces: each item in the `draft` list of `frontend_data.json` gains `confidence` (int or null), `factors` (list of `{label, value}`, possibly empty), and `summary` (string or null). Absent summaries file → summaries omitted (null), section still exports.

- [ ] **Step 1: Add the summaries path and helpers**

In `api_export.py`, below the existing constants:

```python
CURRENT_SEASON = 2025
OUTPUT_PATH = os.path.join('data', 'processed', 'frontend_data.json')
DRAFT_RANKINGS_PATH = os.path.join('data', 'processed', 'draft_rankings.csv')
```

add:

```python
DRAFT_SUMMARIES_PATH = os.path.join('data', 'processed', 'draft_summaries.json')
FACTOR_COLS = [f'factor_{i}' for i in range(1, 7)]


def _load_draft_summaries() -> dict:
    """Load the {playerId: {summary, generated_at, model}} cache, or {} if the
    file is missing/corrupt. Absence is normal (summaries are optional)."""
    if not os.path.exists(DRAFT_SUMMARIES_PATH):
        return {}
    try:
        with open(DRAFT_SUMMARIES_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (ValueError, OSError):
        return {}


def _parse_factors(row) -> list:
    """Parse the factor_1..factor_6 JSON cells into [{label, value}], skipping
    empty/malformed slots. Sign of value encodes direction for the frontend."""
    factors = []
    for col in FACTOR_COLS:
        if col not in row.index:
            continue
        cell = row[col]
        if isinstance(cell, str) and cell:
            try:
                obj = json.loads(cell)
                factors.append({'label': obj['label'],
                                'value': round(float(obj['value']), 3)})
            except (ValueError, KeyError, TypeError):
                pass
    return factors
```

`json` and `os` are already imported at the top of `api_export.py`.

- [ ] **Step 2: Thread the fields through `build_draft_list`**

In `api_export.py`, replace the body of `build_draft_list` (the loop) so it merges summaries and explanations:

```python
    df = pd.read_csv(DRAFT_RANKINGS_PATH)
    summaries = _load_draft_summaries()
    has_confidence = 'confidence' in df.columns
    draft_list = []
    for _, row in df.iterrows():
        player_id = int(row['playerId'])
        entry = summaries.get(str(player_id))
        confidence = None
        if has_confidence and not pd.isna(row['confidence']):
            confidence = int(row['confidence'])
        draft_list.append({
            'id': player_id,
            'full_name': row['full_name'],
            'positionCode': row['position'],
            'headshot': get_headshot_url(player_id),
            'age': round(float(row['age']), 1) if not pd.isna(row['age']) else None,
            'gamesPlayed': int(row['gamesPlayed']),
            'last_fpPerGame': round(float(row['fpPerGame']), 3),
            'projected_fpPerGame': round(float(row['projected_fpPerGame']), 3),
            'projected_total': round(float(row['projected_total']), 1),
            'delta_vs_last': round(float(row['delta_vs_last']), 3),
            'confidence': confidence,
            'factors': _parse_factors(row),
            'summary': entry['summary'] if entry else None,
        })
    return draft_list
```

(The early `if not os.path.exists(DRAFT_RANKINGS_PATH): ... return []` guard at the top of the function stays as-is.)

- [ ] **Step 3: Run the export and verify the draft section**

```bash
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe api_export.py
.\.venv\Scripts\python.exe -c "import json; d=json.load(open('data/processed/frontend_data.json'))['draft'][0]; print('confidence', d['confidence']); print('factors', d['factors'][:2]); print('summary', d['summary'])"
```

Expected: `confidence` is an int, `factors` is a non-empty list of `{label, value}`, `summary` is `None` (no summaries file yet — that is correct). No exception; the draft section still exports.

- [ ] **Step 4: Commit**

```bash
git add api_export.py
git commit -m "feat(draft): export confidence, SHAP factors, and Claude summary per player

```

---

### Task 5: `scripts/build_draft_summaries.py` + `anthropic` dependency

**Files:**
- Create: `scripts/build_draft_summaries.py`
- Modify: `pyproject.toml` (add `anthropic` pin)
- Modify: `requirements.txt` (add `anthropic` pin)

**Interfaces:**
- Consumes: `data/processed/draft_rankings.csv` (Task 3 columns), `ANTHROPIC_API_KEY`.
- Produces: `data/processed/draft_summaries.json` in the contract shape `{playerId(str): {summary, generated_at, model}}`. Resumable (skips cached playerIds), `--force` regenerates, `--top N` bounds the batch (default 200).

Not unit-tested (API script, repo doctrine).

- [ ] **Step 1: Install the dependency and capture the version**

```bash
.\.venv\Scripts\python.exe -m pip install anthropic
.\.venv\Scripts\python.exe -m pip show anthropic
```

Note the `Version:` line (call it `<VER>`). Then verify the SDK imports:

```bash
.\.venv\Scripts\python.exe -c "import anthropic; print(anthropic.__version__)"
```

Expected: prints `<VER>`.

- [ ] **Step 2: Pin it in both dependency files**

In `pyproject.toml`, add `"anthropic==<VER>"` to the `dependencies` list (keep the list's existing style; place it near the top, e.g. right after `"altair==6.2.2",`):

```toml
dependencies = [
    "altair==6.2.2",
    "anthropic==<VER>",
    "anyio==4.14.1",
```

In `requirements.txt`, add a line `anthropic==<VER>` (frozen pin, same value).

- [ ] **Step 3: Write the script**

Create `scripts/build_draft_summaries.py`:

```python
r"""Batch-generate 1-2 sentence Claude summaries for the top draftable players.

Reads data/processed/draft_rankings.csv (built by `python main.py draft`), takes
the top N by projected FP/game, and for each player makes one Claude API call
(model claude-opus-4-8) with web search enabled to reconcile the model's
projection with current real-world context (injury, trade, line/role change).
Writes data/processed/draft_summaries.json:

    {playerId: {"summary": str, "generated_at": iso8601, "model": str}}

The JSON cache is the CONTRACT (see the design doc): any producer that writes
this shape works. This script is the canonical producer; it is resumable
(skips playerIds already cached) and --force regenerates.

Requires ANTHROPIC_API_KEY (pay-as-you-go platform billing -- a claude.ai Pro
subscription does NOT cover API/SDK calls). Fails fast if unset.

    $env:ANTHROPIC_API_KEY = '...'
    .\.venv\Scripts\python.exe scripts/build_draft_summaries.py --top 200

Cost: ~200 calls ~= $8-15 per full refresh at Opus 4.8 rates + per-search fees.
Refresh rarely (pre-draft, maybe once mid-September).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import pandas as pd  # noqa: E402

MODEL = 'claude-opus-4-8'
RANKINGS_PATH = os.path.join(REPO_ROOT, 'data', 'processed', 'draft_rankings.csv')
SUMMARIES_PATH = os.path.join(REPO_ROOT, 'data', 'processed', 'draft_summaries.json')
FACTOR_COLS = [f'factor_{i}' for i in range(1, 7)]


def _load_cache(path: str) -> dict:
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save_cache(path: str, cache: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def _factor_phrases(row) -> str:
    phrases = []
    for col in FACTOR_COLS:
        cell = row.get(col)
        if isinstance(cell, str) and cell:
            try:
                obj = json.loads(cell)
                sign = '+' if obj['value'] >= 0 else '-'
                phrases.append(f"{obj['label']} ({sign}{abs(obj['value']):.2f})")
            except (ValueError, KeyError, TypeError):
                pass
    return '; '.join(phrases) if phrases else 'n/a'


def _build_prompt(row) -> str:
    return (
        "You are helping with a fantasy hockey draft. A machine-learning model "
        "projects next-season performance for this NHL skater:\n\n"
        f"Player: {row['full_name']} ({row['position']}), age {float(row['age']):.0f}\n"
        f"Last season: {float(row['fpPerGame']):.2f} fantasy points per game "
        f"over {int(row['gamesPlayed'])} games\n"
        f"Model projection: {float(row['projected_fpPerGame']):.2f} FP/game next "
        f"season (change of {float(row['delta_vs_last']):+.2f})\n"
        f"Model confidence: {row.get('confidence')}/100\n"
        f"Top model factors (SHAP): {_factor_phrases(row)}\n\n"
        "Search the web for this player's CURRENT situation heading into the "
        "upcoming season -- injuries, trades, line/role or team changes, "
        "contract or coaching news. Then write 1-2 sentences that reconcile the "
        "model's projection with that current context, for a fantasy manager "
        "deciding whether to draft him. Do NOT simply restate the stats above "
        "(the manager can already see them); add the real-world context the "
        "model cannot know. Respond with ONLY the 1-2 sentence summary, no preamble."
    )


def _summarize(client, row) -> str:
    messages = [{'role': 'user', 'content': _build_prompt(row)}]
    tools = [{'type': 'web_search_20260209', 'name': 'web_search', 'max_uses': 3}]
    resp = None
    for _ in range(4):  # allow a few pause_turn continuations for the search loop
        resp = client.messages.create(
            model=MODEL, max_tokens=1024,
            thinking={'type': 'adaptive'},
            tools=tools, messages=messages,
        )
        if resp.stop_reason == 'pause_turn':
            messages.append({'role': 'assistant', 'content': resp.content})
            continue
        break
    return ''.join(b.text for b in resp.content if b.type == 'text').strip()


def main():
    parser = argparse.ArgumentParser(
        description='Batch-generate Claude draft summaries.')
    parser.add_argument('--top', type=int, default=200,
                        help='number of top-projected players to summarize')
    parser.add_argument('--force', action='store_true',
                        help='regenerate summaries even if already cached')
    args = parser.parse_args()

    if not os.environ.get('ANTHROPIC_API_KEY'):
        sys.exit("ANTHROPIC_API_KEY not set. Export it first (pay-as-you-go API "
                 "billing; a claude.ai Pro subscription does not cover API calls).")
    if not os.path.exists(RANKINGS_PATH):
        sys.exit(f"{RANKINGS_PATH} not found -- run "
                 r"'.\.venv\Scripts\python.exe main.py draft' first.")

    import anthropic
    client = anthropic.Anthropic()

    df = (pd.read_csv(RANKINGS_PATH)
          .sort_values('projected_fpPerGame', ascending=False)
          .head(args.top))
    cache = {} if args.force else _load_cache(SUMMARIES_PATH)

    done, failed = 0, 0
    for _, row in df.iterrows():
        pid = str(int(row['playerId']))
        if pid in cache and not args.force:
            continue
        try:
            summary = _summarize(client, row)
            if not summary:
                raise ValueError('empty response')
            cache[pid] = {
                'summary': summary,
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'model': MODEL,
            }
            _save_cache(SUMMARIES_PATH, cache)  # append after each player: resumable
            done += 1
            print(f"[{done}] {row['full_name']}: {summary}")
        except Exception as e:  # per-player failure: log, skip, continue
            failed += 1
            print(f"FAILED {row['full_name']} ({pid}): {e}", file=sys.stderr)

    print(f"\nDone: {done} generated, {failed} failed, {len(cache)} total in cache.")


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Verify import + fail-fast + `--help` (no API key needed)**

```bash
.\.venv\Scripts\python.exe -c "import main"
.\.venv\Scripts\python.exe scripts/build_draft_summaries.py --help
```

Expected: `import main` exits 0 (dependency installed, nothing broke). `--help` prints usage. Then confirm the fail-fast path without a key:

```bash
.\.venv\Scripts\python.exe -c "import os; os.environ.pop('ANTHROPIC_API_KEY', None); import runpy, sys; sys.argv=['x']; runpy.run_path('scripts/build_draft_summaries.py', run_name='__main__')"
```

Expected: exits with the "ANTHROPIC_API_KEY not set" message (SystemExit), not a traceback into the SDK.

- [ ] **Step 5: Confirm `draft_summaries.json` is gitignored**

```bash
git check-ignore data/processed/draft_summaries.json
```

Expected: prints the path (matched by the blanket `data/` ignore). If it prints nothing, add `data/processed/draft_summaries.json` to `.gitignore` and re-check.

- [ ] **Step 6: Commit (code + pins only — never the JSON or model)**

```bash
git add scripts/build_draft_summaries.py pyproject.toml requirements.txt
git commit -m "feat(draft): canonical Claude summary producer + anthropic dependency

```

---

### Task 6: Frontend — confidence column + expandable draft detail

**Files:**
- Modify: `frontend/src/types/player.ts` (extend `DraftPlayer`)
- Modify: `frontend/src/components/rink/bits.tsx` (`ScoreMeter` neutral tone)
- Modify: `frontend/src/components/rink/bits.module.css` (`.meterNeutral`)
- Modify: `frontend/src/components/rink/DraftBoard.tsx` (confidence column + expandable row)
- Modify: `frontend/src/components/rink/RinkTable.module.css` (factor list + summary styles)

**Interfaces:**
- Consumes: the `draft` items from Task 4 (`confidence`, `factors`, `summary`).
- Produces: a compact confidence column and a click-to-expand detail row per draft player.

- [ ] **Step 1: Extend the `DraftPlayer` type**

In `frontend/src/types/player.ts`, add a `DraftFactor` type and three fields to `DraftPlayer`:

```typescript
// One SHAP factor behind a draft projection. Positive value pushed the ranking
// up, negative pulled it down (the frontend colours by sign).
export interface DraftFactor {
  label: string;
  value: number;
}

// Season-level draft projection row (from main.py draft -> api_export.py).
// Distinct shape from Player: no live/last-5 stats, projection fields instead.
export interface DraftPlayer {
  id: number;
  full_name: string;
  positionCode: Position;
  headshot: string;
  age: number | null;
  gamesPlayed: number;
  last_fpPerGame: number;
  projected_fpPerGame: number;
  projected_total: number;
  delta_vs_last: number;
  confidence: number | null;
  factors: DraftFactor[];
  summary: string | null;
}
```

- [ ] **Step 2: Give `ScoreMeter` a neutral tone**

In `frontend/src/components/rink/bits.tsx`, change `ScoreMeter` to accept a neutral tone (confidence is not hot/cold):

```tsx
/** Thin 0–100 meter for model scores; red for heat, blue for cool, grey neutral. */
export function ScoreMeter({
  value,
  tone,
}: {
  value: number;
  tone: Tone | 'neutral';
}) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  const fillClass =
    tone === 'hot'
      ? styles.meterHot
      : tone === 'cold'
        ? styles.meterCold
        : styles.meterNeutral;
  return (
    <div className={styles.meter}>
      <div
        className={styles.meterTrack}
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
      >
        <div className={`${styles.meterFill} ${fillClass}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={styles.meterValue}>{pct}</span>
    </div>
  );
}
```

- [ ] **Step 3: Add the neutral meter fill colour**

In `frontend/src/components/rink/bits.module.css`, find the `.meterHot` / `.meterCold` rules and add alongside them:

```css
.meterNeutral {
  background: var(--ink-3);
}
```

(`var(--ink-3)` is the same neutral used by `.paceBarNeutral` in `RinkTable.module.css`.)

- [ ] **Step 4: Add factor-list + summary styles**

In `frontend/src/components/rink/RinkTable.module.css`, append (reuses the existing `.detail`, `.detailBlock`, `.detailHeading` grid/heading styles):

```css
/* Draft detail: summary text + SHAP factor list */
.summaryText {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.5;
  color: var(--ink);
}

.summaryEmpty {
  color: var(--ink-3);
}

.factorList {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.factorItem {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  font-size: 13px;
}

.factorLabel {
  color: var(--ink-2);
}

.factorValue {
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.factorUp .factorValue {
  color: var(--hot);
}

.factorDown .factorValue {
  color: var(--cold);
}
```

- [ ] **Step 5: Rewrite `DraftBoard.tsx` with the confidence column + expandable detail**

Replace the entire contents of `frontend/src/components/rink/DraftBoard.tsx` with:

```tsx
'use client';

import { Fragment, useMemo, useState } from 'react';
import type { DraftPlayer, Position } from '@/types/player';
import { Headshot, PositionChip, ScoreMeter } from './bits';
import styles from './RinkTable.module.css';
import bitStyles from './bits.module.css';

type SortDir = 'asc' | 'desc';

interface Column {
  key: string;
  label: string;
  title?: string;
  numeric?: boolean;
  sortValue?: (p: DraftPlayer) => number | string;
  render: (p: DraftPlayer) => React.ReactNode;
}

/** Signed projection-change chip: red when projected above last season, blue below. */
function ProjectionDeltaChip({ value }: { value: number }) {
  const label = `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toFixed(2)}`;
  const cls =
    value >= 0.1
      ? bitStyles.deltaHot
      : value <= -0.1
        ? bitStyles.deltaCold
        : bitStyles.deltaFlat;
  return (
    <span
      className={`${bitStyles.delta} ${cls}`}
      title="Projected FP per game vs. last season"
    >
      {label}
    </span>
  );
}

const COLUMNS: Column[] = [
  {
    key: 'full_name',
    label: 'Player',
    sortValue: (p) => p.full_name,
    render: (p) => (
      <span className={styles.playerCell}>
        <Headshot src={p.headshot} name={p.full_name} size={32} />
        <span className={styles.playerName}>{p.full_name}</span>
        <PositionChip position={p.positionCode} />
      </span>
    ),
  },
  {
    key: 'age',
    label: 'Age',
    title: 'Age at next season start',
    numeric: true,
    sortValue: (p) => p.age ?? 0,
    render: (p) => (p.age === null ? '—' : p.age.toFixed(1)),
  },
  {
    key: 'gamesPlayed',
    label: 'GP',
    title: 'Games played last season',
    numeric: true,
    sortValue: (p) => p.gamesPlayed,
    render: (p) => p.gamesPlayed,
  },
  {
    key: 'last_fpPerGame',
    label: 'FP/G',
    title: 'Fantasy points per game last season',
    numeric: true,
    sortValue: (p) => p.last_fpPerGame,
    render: (p) => p.last_fpPerGame.toFixed(2),
  },
  {
    key: 'projected_fpPerGame',
    label: 'Proj FP/G',
    title: 'Model-projected fantasy points per game next season',
    numeric: true,
    sortValue: (p) => p.projected_fpPerGame,
    render: (p) => <strong>{p.projected_fpPerGame.toFixed(2)}</strong>,
  },
  {
    key: 'projected_total',
    label: 'Proj FP',
    title: 'Projected season total (FP per game × 78 games)',
    numeric: true,
    sortValue: (p) => p.projected_total,
    render: (p) => p.projected_total.toFixed(0),
  },
  {
    key: 'delta_vs_last',
    label: 'Δ',
    title: 'Projected minus last-season FP per game',
    numeric: true,
    sortValue: (p) => p.delta_vs_last,
    render: (p) => <ProjectionDeltaChip value={p.delta_vs_last} />,
  },
  {
    key: 'confidence',
    label: 'Conf',
    title: 'Model confidence (data depth + projection stability), 0–100',
    numeric: true,
    sortValue: (p) => p.confidence ?? -1,
    render: (p) =>
      p.confidence === null ? (
        '—'
      ) : (
        <ScoreMeter value={p.confidence / 100} tone="neutral" />
      ),
  },
];

function ExpandedDraftDetail({ player }: { player: DraftPlayer }) {
  return (
    <div className={styles.detail}>
      <div className={styles.detailBlock}>
        <h4 className={styles.detailHeading}>Scouting summary</h4>
        {player.summary ? (
          <p className={styles.summaryText}>{player.summary}</p>
        ) : (
          <p className={`${styles.summaryText} ${styles.summaryEmpty}`}>—</p>
        )}
      </div>

      <div className={styles.detailBlock}>
        <h4 className={styles.detailHeading}>Confidence</h4>
        {player.confidence === null ? (
          <p className={`${styles.summaryText} ${styles.summaryEmpty}`}>—</p>
        ) : (
          <ScoreMeter value={player.confidence / 100} tone="neutral" />
        )}
      </div>

      <div className={styles.detailBlock}>
        <h4 className={styles.detailHeading}>What moved the ranking</h4>
        {player.factors.length === 0 ? (
          <p className={`${styles.summaryText} ${styles.summaryEmpty}`}>—</p>
        ) : (
          <ul className={styles.factorList}>
            {player.factors.map((f, i) => (
              <li
                key={i}
                className={`${styles.factorItem} ${
                  f.value >= 0 ? styles.factorUp : styles.factorDown
                }`}
              >
                <span className={styles.factorLabel}>{f.label}</span>
                <span className={styles.factorValue}>
                  {f.value >= 0 ? '+' : '−'}
                  {Math.abs(f.value).toFixed(2)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default function DraftBoard({ players }: { players: DraftPlayer[] }) {
  const [sortKey, setSortKey] = useState('projected_fpPerGame');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [position, setPosition] = useState<Position | 'ALL'>('ALL');
  const [query, setQuery] = useState('');
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const rows = useMemo(() => {
    let data = players;
    if (position !== 'ALL') data = data.filter((p) => p.positionCode === position);
    if (query) {
      const q = query.toLowerCase();
      data = data.filter((p) => p.full_name.toLowerCase().includes(q));
    }
    const col = COLUMNS.find((c) => c.key === sortKey);
    if (col?.sortValue) {
      const dir = sortDir === 'asc' ? 1 : -1;
      data = [...data].sort((a, b) => {
        const av = col.sortValue!(a);
        const bv = col.sortValue!(b);
        if (typeof av === 'string' || typeof bv === 'string') {
          return String(av).localeCompare(String(bv)) * dir;
        }
        return (av - (bv as number)) * dir;
      });
    }
    return data;
  }, [players, position, query, sortKey, sortDir]);

  function toggleSort(col: Column) {
    if (!col.sortValue) return;
    if (sortKey === col.key) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortKey(col.key);
      setSortDir(col.key === 'full_name' ? 'asc' : 'desc');
    }
  }

  const positions: (Position | 'ALL')[] = ['ALL', 'C', 'L', 'R', 'D'];

  return (
    <section className={styles.section} aria-label="Draft board">
      <div className={styles.controls}>
        <input
          type="search"
          className={styles.search}
          placeholder="Search players"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search players by name"
        />
        <div className={styles.positions} role="group" aria-label="Filter by position">
          {positions.map((pos) => (
            <button
              key={pos}
              className={`${styles.posButton} ${position === pos ? styles.posActive : ''}`}
              onClick={() => setPosition(pos)}
              aria-pressed={position === pos}
            >
              {pos}
            </button>
          ))}
        </div>
        <span className={styles.count}>
          {rows.length} skater{rows.length === 1 ? '' : 's'}
        </span>
      </div>

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.thRank} scope="col">
                No.
              </th>
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  scope="col"
                  title={col.title}
                  className={col.numeric ? styles.thNumeric : undefined}
                  aria-sort={
                    sortKey === col.key
                      ? sortDir === 'asc'
                        ? 'ascending'
                        : 'descending'
                      : undefined
                  }
                >
                  <button className={styles.thButton} onClick={() => toggleSort(col)}>
                    {col.label}
                    <span className={styles.sortMark} aria-hidden="true">
                      {sortKey === col.key ? (sortDir === 'asc' ? '▲' : '▼') : ''}
                    </span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={COLUMNS.length + 1} className={styles.empty}>
                  No players match. Clear the search or position filter to see the
                  full list.
                </td>
              </tr>
            )}
            {rows.map((p, i) => (
              <Fragment key={p.id}>
                <tr
                  className={`${styles.row} ${expandedId === p.id ? styles.rowOpen : ''}`}
                  onClick={() => setExpandedId(expandedId === p.id ? null : p.id)}
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      setExpandedId(expandedId === p.id ? null : p.id);
                    }
                  }}
                  aria-expanded={expandedId === p.id}
                >
                  <td className={styles.rank}>{i + 1}</td>
                  {COLUMNS.map((col) => (
                    <td
                      key={col.key}
                      className={col.numeric ? styles.tdNumeric : undefined}
                    >
                      {col.render(p)}
                    </td>
                  ))}
                </tr>
                {expandedId === p.id && (
                  <tr className={styles.detailRow}>
                    <td colSpan={COLUMNS.length + 1}>
                      <ExpandedDraftDetail player={p} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
```

- [ ] **Step 6: Typecheck / build the frontend**

```bash
cd frontend; npm run build
```

Expected: the build (or `next lint` / `tsc`) succeeds with no type errors on `DraftPlayer`, `ScoreMeter`, or `DraftBoard`. If the project has a faster `npm run lint` or `npx tsc --noEmit`, run that instead/as well.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/types/player.ts frontend/src/components/rink/bits.tsx frontend/src/components/rink/bits.module.css frontend/src/components/rink/DraftBoard.tsx frontend/src/components/rink/RinkTable.module.css
git commit -m "feat(rink): confidence column + expandable draft detail (summary, factors)

```

---

### Task 7 (data run, optional — not code): generate real summaries

The script in Task 5 is the canonical producer but needs `ANTHROPIC_API_KEY` (pay-as-you-go; the owner's claude.ai Pro subscription does not cover it). Because `draft_summaries.json` is the contract, an alternative producer is a **Claude Code session** (covered by Pro): read `data/processed/draft_rankings.csv`, use web search per player, and write the same `{playerId: {summary, generated_at, model}}` shape to `data/processed/draft_summaries.json`, in chunks to respect session limits.

Either way, after summaries exist:

- Re-run `.\.venv\Scripts\python.exe api_export.py` so `frontend_data.json` picks up the `summary` strings.
- **Eyeball gate** (design §4): spot-check 5 generated summaries against known player situations (a player known to be injured/traded should read correctly) before trusting the batch.

This task produces gitignored data, not code — do not commit its output.

---

## Notes for the executor

- Work the tasks in order; each ends at a green checkpoint and a commit, so the session can stop after any task and resume cleanly.
- Tasks 1–4 need only the already-present local model + CSVs (no API key). Task 5's API-dependent run is out of scope for the build; its `--help`/fail-fast/import checks are enough to land the code. Task 6 is pure frontend. Task 7 is a data run, optional.
- Do not commit `data/processed/draft_summaries.json`, `frontend_data.json`, `draft_rankings.csv`, or any `models/**/*.pkl` — all gitignored.
