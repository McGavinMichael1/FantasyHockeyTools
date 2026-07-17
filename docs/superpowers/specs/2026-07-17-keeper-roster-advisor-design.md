# Keeper roster advisor chat - design

Drafted and approved with the owner on 2026-07-17.

## Problem

The keeper analyzer provides a defensible quantitative top four, but its current
LLM layer generates one cached paragraph from only those four players. It cannot
answer follow-up questions, compare the recommended players with the rest of the
roster, or account for information outside the projection model. This matters
for players such as Wyatt Johnston and Matvei Michkov, whose age and development
upside may justify a manager accepting less projected value for a longer-term
bet.

The existing summary cache is also keyed only by season. Its candidate ids can
become stale after the projection board changes while the old paragraph remains
eligible for reuse.

## Goals

- Add a live, roster-scoped chat to the keeper page.
- Preserve the deterministic keeper model as the quantitative source of truth.
- Give the assistant the complete roster, relevant historical data, league
  rules, and league-wide comparisons rather than only the recommended four.
- Let the assistant recommend a different keeper set when qualitative or
  current evidence justifies it.
- Make every divergence from the model conspicuous and quantify its projected
  cost.
- Use live research only when current information could materially affect the
  answer.
- Retain preferences and scenario assumptions across follow-up questions in the
  same conversation.
- Keep the deterministic keeper board useful when the LLM, its API key, or web
  research is unavailable.

## Approved product decisions

1. The assistant considers the model ranking, league rules, and player context;
   it does not merely explain the model's official top four.
2. A recommendation that differs from the model must be labeled as a divergence
   and identify the external or qualitative evidence responsible.
3. The assistant infers whether a question is about next season, multi-year
   value, or a balanced view. It defaults to balanced when the question does not
   specify a horizon.
4. Live research runs only for questions that depend on current information.
5. The interaction is a real multi-turn chat with shared conversation context.
6. The integrated, server-side chat on the existing keeper page is the chosen
   architecture.

## Non-goals for v1

- Changing or retraining the skater or goalie projection models.
- Turning qualitative youth upside into invented fantasy-point projections.
- Automatically submitting keepers to Yahoo.
- Performing background research on every roster player.
- Adding a server-side conversation database or user accounts.
- Making the LLM responsible for fantasy scoring, replacement levels, keeper
  costs, or other deterministic arithmetic.

## Architecture

```text
MoneyPuck/NHL/Yahoo inputs
          |
          v
existing projection + keeper pipeline (Python; source of truth)
          |
          +--> keeper_rankings.csv (complete roster)
          |
          +--> keeper_advisor_context.json (versioned decision context)
                              |
                              v
                  server-only Next.js chat route
                     |                   |
                     |                   +--> live web search, only when needed
                     v
                  LLM response
                     |
                     v
              keeper-page chat thread
```

The Python pipeline owns all hockey data preparation and model-derived values.
The Next.js route owns LLM orchestration, tool execution over the generated
context, response validation, and provider error handling. The browser owns
presentation and local conversation persistence. API credentials and the raw
advisor context never reach client-side JavaScript.

### Python context builder

A focused `src/keeper_advisor.py` module builds the advisor context after
`keeper.analyze_keepers()` has produced the complete roster ranking. It consumes
existing outputs; it does not introduce another scoring or projection path.

`main.py keeper` writes both:

- `data/processed/keeper_rankings.csv`, retaining its current complete-roster
  contract; and
- `data/processed/keeper_advisor_context.json`, a gitignored, server-only
  artifact.

The context builder reads the canonical values already used by the product:

- `src.fantasyPoints` scoring weights;
- `src.keeper` keeper count, keeper rounds, replacement ranks, replacement
  levels, and keeper values;
- the authenticated Yahoo roster and any league metadata available through the
  existing Yahoo integration;
- `player_seasons.csv` for skater history and `goalie_seasons.csv` for goalie
  history; and
- the combined current projection board for positional and league-wide ranks.

A league rule that is unavailable from the existing code or Yahoo response is
serialized as `unknown`; the assistant must disclose the missing rule when it
is material rather than infer it.

### Context contract

The JSON artifact has a versioned schema and a content-derived identity:

```json
{
  "schema_version": 1,
  "context_id": "sha256-of-canonical-decision-payload",
  "generated_at": "ISO-8601 timestamp",
  "season": "2026-27",
  "league": {},
  "official_top_four": [],
  "roster": [],
  "scenario_data": {}
}
```

`context_id` hashes the canonical decision payload, excluding volatile fields
such as `generated_at`. It changes when the roster, relevant history,
projections, model factors, or league rules change, but not when the same inputs
are regenerated.

For each roster player, the artifact includes:

- stable id, name, position, and roster eligibility;
- official keeper rank and recommendation status;
- last-season games and FP/game;
- projected FP/game, projected games, projected total, and change from last
  season;
- replacement level, raw keeper value, assigned round, pick cost, and net
  keeper value where applicable;
- model confidence and explanatory factors;
- age, career games, and up to three completed seasons of relevant skater or
  goalie history; and
- positional rank, VORP rank, and comparisons with the official keeper cutoff.

"All the data" means this compact decision dossier, not raw MoneyPuck rows.
The full historical CSVs and league-wide projection table remain server-side
inputs to the builder and are reduced to the facts needed for keeper decisions.

`scenario_data` contains deterministic results needed for interactive what-if
questions. The Python builder precomputes the model value and round assignment
for valid four-player combinations among roster players with complete model
values, which is small for an approximately 18-player roster. Players with
missing values remain in the roster dossier but are excluded from combinations
with an explicit reason. Server tools can then answer "lock Michkov," "exclude
Fox," or "what does Johnston cost me?" by looking up exact precomputed values
instead of asking the LLM to perform arithmetic or reimplementing keeper math in
TypeScript.

## Chat API

A server-only Next.js route, `POST /api/keeper-chat`, accepts:

```json
{
  "context_id": "expected-context-id",
  "messages": [
    {"role": "user", "content": "Why not Wyatt Johnston?"}
  ],
  "conversation_summary": null
}
```

The route rejects a request whose `context_id` does not match the current
artifact and returns a typed `stale_context` response. It limits message size,
turn count, and total request size before calling the provider.

Every prompt receives a compact roster index and the official top four so all
roster names and the baseline recommendation are resolvable. The route then
loads only the detailed player dossiers and deterministic scenario results
relevant to the current question and conversation. It does not place the entire
context file in every prompt. Provider/model selection is server configuration
through `KEEPER_ADVISOR_MODEL`; the API key remains `ANTHROPIC_API_KEY`, matching
the repo's existing LLM integration. A provider client or tool version may
change without changing the advisor context contract.

### Research policy

The LLM may invoke live web search when the question or current turn depends on
information such as:

- injury or recovery status;
- trades, contracts, or roster moves;
- current line, power-play, or goalie deployment;
- recent coaching decisions or public comments;
- recent prospect development; or
- a claim whose truth may have changed since the local data snapshot.

Projection math, historical comparisons, league rules, and deterministic
what-if calculations do not trigger research by themselves. The UI's
`research_used` value comes from actual tool execution, never from model prose.

Source priority is official NHL/team material first, followed by established
reporting. Rumors and social posts are admissible only when explicitly labeled
unconfirmed. Retrieved web content is untrusted evidence: it cannot override
system instructions, request secrets, or alter the local model values.

If research fails, the route may answer from local data but must set
`current_information_verified` to false and say so in the response.

### Response contract

The route validates a structured response before returning it:

```json
{
  "stance": "agrees | diverges | conditional",
  "objective": "next_season | multi_year | balanced",
  "answer": "concise conversational answer",
  "model_view": "what the deterministic ranking says",
  "recommendation": "the assistant's recommendation",
  "tradeoff": {
    "out_player_id": null,
    "in_player_id": null,
    "projected_keeper_value_cost": null
  },
  "qualitative_factors": [],
  "uncertainty": [],
  "research": {
    "used": false,
    "current_information_verified": null,
    "as_of": null,
    "sources": []
  }
}
```

Every answer must:

1. state the model's position;
2. state the assistant's recommendation;
3. label the stance as agrees, diverges, or conditional;
4. name the exact swap and deterministic projected cost when diverging;
5. separate model evidence from qualitative or external evidence;
6. cite and date live sources when research was used; and
7. state material uncertainty.

Age, trajectory, and development upside may support a qualitative decision,
but they must not be presented as model-generated fantasy points. The system
prompt also forbids invented injuries, roles, league rules, statistics, and
sources.

`projected_keeper_value_cost` always describes the deterministic next-season
model trade-off, even when the inferred objective is balanced or multi-year. It
is `null` unless the answer recommends a specific divergence. Likewise,
`current_information_verified` is `null` when current information is not needed,
`true` after successful live verification, and `false` when current information
was material but could not be verified.

Each researched source contains a required title, URL, and retrieval timestamp,
plus a publication date when the source exposes one. The answer's `as_of` value
is always present when research was attempted.

## Conversation behavior

The keeper page replaces the current "Cached manager note" panel with a roster
advisor chat while keeping the deterministic keeper cards visible. Suggested
opening prompts include:

- "Why not Wyatt Johnston?"
- "Build me a youth-focused keeper set."
- "Compare Matvei Michkov with my fourth keeper."

The browser stores a conversation under its `context_id`. Reloading the page
restores that conversation. A "New conversation" action clears assumptions for
the current context.

When `context_id` changes, the old conversation remains readable but is visibly
marked stale and cannot accept new messages. The page starts a fresh thread for
the new context. Older turns may be compacted into a conversation summary, but
the summary must retain explicit preferences, locked/excluded players, accepted
swaps, the inferred objective, and previously cited findings.

The UI renders:

- an `Agrees`, `Diverges`, or `Conditional` badge;
- the inferred objective;
- the answer and deterministic model trade-off;
- model evidence separately from qualitative/current context;
- a "Live research used" indicator when applicable; and
- linked source titles and publication dates.

## Superseded cached summary

The live chat supersedes `scripts/build_keeper_summary.py` and the keeper page's
once-per-season manager note. The implementation removes that panel and its
setup instructions, stops exporting it as active keeper-page content, and
ignores legacy `keeper_summary.json` files. This avoids competing advice and
eliminates the season-only invalidation bug. The deterministic cards remain the
page's default answer before the first chat turn.

## Failure behavior

- **Missing advisor context:** keep the ranking cards visible and show the
  command needed to regenerate the keeper analysis.
- **Missing API key:** disable chat with a configuration message; do not hide or
  alter rankings.
- **Provider timeout/error:** preserve the user's unsent or failed turn and
  offer retry.
- **Web research failure:** answer locally only when useful and mark current
  information as unverified.
- **Malformed LLM output:** validate server-side, retry once with the validation
  errors, then return a typed failure rather than render partial advice.
- **Stale context:** make the prior thread read-only and start a new thread
  against the current context.
- **Missing player match or historical field:** retain the player with an
  explicit missing-data marker; never silently remove the player from the
  advisor context.

## Security and privacy

- `ANTHROPIC_API_KEY` is read only by the server route.
- The raw advisor context is never returned to the browser.
- Requests accept only user/assistant text roles and enforce size limits.
- Tool inputs are validated against player ids and scenarios present in the
  current context; there is no arbitrary file or command access.
- Web results are evidence only and are never allowed to modify instructions or
  access local data.
- Generated context and chat history remain local and gitignored.

## Testing

### Python pure-function tests

- Context includes every roster row, not only the official top four.
- Skater and goalie histories are reduced to the agreed fields.
- Canonical league settings and scoring weights are serialized without prompt
  copies.
- `context_id` is stable for identical decision inputs and changes for roster,
  projection, factor, or league-rule changes.
- Scenario values and round assignments match `src.keeper` for hand-computed
  fixtures, including locked and excluded players.
- Missing history is represented explicitly without dropping a roster player.

### Route tests with mocked provider/tools

- Local model questions do not invoke web search.
- current injury/news/deployment questions can invoke web search.
- Divergence responses require an exact swap and deterministic cost.
- Researched responses require source urls, titles, dates, and an as-of date.
- Stale context, missing key, provider timeout, web failure, and malformed JSON
  produce their typed failure behaviors.
- Prompt-injection text in a mocked web result does not alter the response
  contract or expose context/secrets.

### Frontend tests

- Messages and inferred preferences persist across follow-ups and reloads.
- `Agrees`, `Diverges`, and `Conditional` responses render distinctly.
- Research indicators and source links render only from validated metadata.
- A changed `context_id` makes the old conversation read-only and starts a new
  one.
- The deterministic keeper board remains usable for every chat failure state.

### Manual acceptance gate

1. "Why not Wyatt Johnston?" explains the official ranking and either defends
   it or clearly quantifies a judgment-based override.
2. "Has Matvei Michkov's outlook changed recently?" performs dated, sourced
   research.
3. "Prioritize youth" followed by "Then who gets dropped?" retains the shared
   scenario and names the exact swap.
4. Regenerating the keeper board with changed inputs marks the old conversation
   stale.
5. Removing the API key leaves the deterministic keeper cards intact.

## Implementation boundaries

The work should be planned as four independently testable slices:

1. Python advisor context and scenario generation.
2. Server-side chat/research route and response validation.
3. Keeper-page chat, local persistence, and stale-context UX.
4. Cached-summary retirement, failure-state polish, and end-to-end acceptance.

No slice changes scoring weights, model features, train/validation splits, or
saved model behavior.
