# MoneyPuck goalie data

Manual browser downloads from https://moneypuck.com/data.htm (no auto-downloader,
by design — MoneyPuck requires a data license for scrapers). All four files carry
the same MoneyPuck goalie column set (icetime, xGoals, goals, ongoal, rebounds,
danger-band splits, ...) and one row per **situation** (`all`, `5on5`, `5on4`,
`4on5`, `other`) — the `'all'` row already totals the others, so never sum raw
rows across situations (same double-count trap as the skater files).

| File | Grain | Coverage | MoneyPuck source |
| --- | --- | --- | --- |
| `goalies_current_seasons.csv` | one row per goalie-season-situation | 2025 (= 2025-26) | season-level "Goalies" CSV, current season |
| `goalies_current_gamedata.csv` | one row per goalie-game-situation | 2025 (= 2025-26) | game-by-game goalie data, current season |
| `goalies_2008_to_2024_seasons.csv` | one row per goalie-season-situation | 2008–2024 | season-level "Goalies" CSV, historical |
| `goalies_2008_to_2024_gamedata.csv` | one row per goalie-game-situation | 2008–2024 | game-by-game goalie data, historical |

Identified 2026-07-16: game-grain files have `gameId`/`gameDate`/`opposingTeam`
columns; season-grain files have `games_played` and no game columns.

**What MoneyPuck goalie data does NOT contain:** wins, losses, shutouts, games
started — it is shot/xGoals data only (`goals` = goals against, saves are
derivable as `ongoal - goals`). Fantasy goalie scoring (GS/W/L/GA/SV/SHO) needs
the NHL API landing endpoint's `seasonTotals` merged in — see
`scripts/build_goalie_seasons.py` (goalie draft/keeper pipeline).

Season files feed the draft/keeper goalie ranker. Game-grain files are not used
by the draft pipeline; they are staged for the future goalie-streaming feature.

Refresh cadence: same as the skater CSVs — re-download the current-season files
when refreshing data, and roll `current` into the historical files' range at
season rollover (see `fht-operations`).
