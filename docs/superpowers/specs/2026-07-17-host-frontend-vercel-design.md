# Host the frontend on Vercel for the league — design

Date: 2026-07-17
Status: design, awaiting review (no code written yet)

## Goal

Make the Next.js dashboard reachable by the 9 other members of Yahoo league
`nhl.l.33072`, with the least operational overhead. The Python ML pipeline stays
local; only the frontend is hosted.

## Decisions locked with the owner

- **Host target:** Vercel (native Next.js App Router + serverless API routes; free
  tier covers 10 users).
- **What is hosted:** the `frontend/` Next.js app only. The Python pipeline, the 2.6 GB
  MoneyPuck CSVs, and the trained models stay on the owner's machine (MoneyPuck-license
  and size reasons — see `fht-architecture-contract`).
- **First ship scope:** viewer tables only — pickups, cooling, draft board, keeper board.
  The AI keeper-chat advisor is **deferred** to a later pass.
- **Access control:** one shared password via HTTP Basic Auth (protects the whole site,
  including — later — the paid keeper-chat route so outsiders can't spend the owner's
  Anthropic credits).
- **Data refresh:** manual redeploy via the Vercel CLI (`vercel --prod`), which uploads the
  local working directory. The site shows whatever JSON was bundled at the last deploy;
  freshness is surfaced by the existing `dataAge` badge from the JSON's own `generated_at`.
- **JSON delivery:** build-time bundle (Approach A below), kept out of git and shipped by
  the CLI upload (see "How the JSON reaches the deploy").
- **Vercel account:** Hobby (free, non-commercial) tier. The CLI and login cost nothing.
- **Advisor hiding mechanism:** a `NEXT_PUBLIC_ENABLE_ADVISOR` feature flag.

## Why this shape

The frontend is *not* a static site. Two server API routes read files off disk at
request time, and both target paths **outside** `frontend/` (`../data/processed/`),
which a cloud deploy of `frontend/` does not include:

- `frontend/src/app/api/players/route.ts` → `../data/processed/frontend_data.json`
- `frontend/src/lib/keeperAdvisorContext.ts` → `../data/processed/keeper_advisor_context.json`
  (used only by the deferred keeper-chat route)

Plus `frontend/src/app/api/keeper-chat/route.ts` calls the Anthropic API server-side and
needs `ANTHROPIC_API_KEY` + `KEEPER_ADVISOR_MODEL`. Deferring the advisor removes that
route, its context file, and the API key from the first ship — a materially simpler first
deploy.

## JSON delivery — Approach A (build-time bundle)

The refresh step copies `frontend_data.json` into `frontend/data/`, and the players route
reads it from that bundled location instead of `../data/processed/`.

**How the route reads it (guaranteed-bundling form):** use a static
`import data from '@/data/frontend_data.json'` rather than a runtime `readFileSync`. A
static import is resolved by the bundler at build time, so the data is guaranteed to be in
the function — no reliance on Next.js file-tracing following a dynamic `readFileSync` path
(which is not guaranteed on Vercel serverless). Consequences for the current route:

- The `existsSync` → 404 branch goes away (a missing file becomes a build-time error, which
  is what we want — you can't deploy stale-less). Keep a light guard only if desired.
- The `statSync` mtime fallback goes away; `dataAge` is computed purely from the JSON's
  `generated_at` field, which the export always sets.

Rejected alternative — Approach B (serve the JSON from `public/`, client fetches it
directly): drops the API route's 404 and age-badge logic and touches more of the working
UI for no benefit at this scale.

### How the JSON reaches the deploy

Vercel's *git integration* only ships committed files, but deploying with the **Vercel CLI**
(`vercel --prod`) uploads the local working directory and honours `.vercelignore`, **not**
`.gitignore`. So the bundled JSON can stay out of git entirely and still ship:

- `frontend/data/` is added to `.gitignore` (the JSON is an 864 KB generated artifact;
  keeping it untracked avoids ~0.9 MB of git-history growth per refresh, consistent with
  the repo's "data outputs are not versioned" rule).
- A `.vercelignore` must **not** exclude `frontend/data/`, so the CLI upload includes it.
- The refresh step recreates `frontend/data/frontend_data.json` locally before each
  `vercel --prod`.

Deploy is CLI-driven, not git-push-driven. Git integration for the project is left
unconnected (or, if connected, simply unused — deploys always go through the CLI).

## Components to add / change

1. **Bundle location + route repoint.** New `frontend/data/` (gitignored). Replace the
   players route's `readFileSync(../data/processed/...)` with a static import of the bundled
   `frontend/data/frontend_data.json` (import path must resolve to that file — via a
   relative import or a new tsconfig path alias). No change to the response shape the UI
   consumes.

2. **Password gate.** New `frontend/middleware.ts` performing HTTP Basic Auth against a
   `SITE_PASSWORD` env var, matching all routes (`config.matcher`). Returns
   `401 WWW-Authenticate: Basic` when absent/wrong. One shared password handed to the
   league.

3. **Advisor feature flag.** Guard the `<KeeperAdvisor>` render in
   `frontend/src/app/keeper/page.tsx:182` behind `NEXT_PUBLIC_ENABLE_ADVISOR === '1'`.
   Unset in the hosted build → the keeper *board* still renders, the *chat* is hidden.
   Set locally → unchanged dev experience. The keeper-chat route code stays in the repo
   untouched; it is simply never hit from the hosted UI and never configured with a key.

4. **`.vercelignore`.** New `frontend/.vercelignore` mirroring the usual build excludes
   (`node_modules/`, `.next/`, test build dirs) but **not** `data/`, so the CLI upload
   includes the bundled JSON.

5. **Vercel project config.** One-time: `vercel login` (free Hobby account), then
   `vercel link` with **Root Directory = `frontend`**; set `SITE_PASSWORD` via
   `vercel env add` (or the dashboard). No Anthropic key this ship. (Checklist, not code.)

6. **Refresh runbook.** Documented manual loop:
   1. Run the pipeline locally (`api_export.py`, per `fht-operations`).
   2. Copy `data/processed/frontend_data.json` → `frontend/data/frontend_data.json`.
   3. From `frontend/`: `vercel --prod`.

## Deferred: AI keeper advisor (later pass, documented, not built now)

To turn the advisor on later: bundle `keeper_advisor_context.json` into `frontend/data/`
the same way; add `ANTHROPIC_API_KEY` + `KEEPER_ADVISOR_MODEL` to Vercel env; set
`NEXT_PUBLIC_ENABLE_ADVISOR=1`. The password gate already protects the paid route. Cost at
10-user scale is expected to be cents-to-low-dollars, but gating is what bounds it.

## Explicitly out of scope

- No changes to the Python pipeline, scoring, models, or feature code.
- No committing of data/model artifacts (they stay gitignored).
- No automated refresh/CI — manual redeploy by owner decision.
- No per-user accounts — one shared password only.

## Testing / verification

- Frontend already runs end-to-end locally against real `frontend_data.json`
  (owner-confirmed), so the baseline works.
- Local check before deploy: with `frontend/data/frontend_data.json` present and
  `NEXT_PUBLIC_ENABLE_ADVISOR` unset, `npm run build && npm start` in `frontend/` renders
  the pickups/cooling/draft/keeper tables and hides the advisor chat.
- Middleware check: request without credentials returns 401; with the `SITE_PASSWORD`
  Basic-Auth header returns the app.
- Post-deploy smoke test: hit the Vercel URL, confirm password prompt, confirm tables load
  and `dataAge` badge shows the export age.

## Open questions

None outstanding — all forks resolved with the owner.
