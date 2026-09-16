# Yahoo Fantasy API Setup (Optional)

The Yahoo API integration allows the app to filter out already-rostered players from pickup recommendations.

**Note**: This is completely optional. The app will work without it - it just won't filter out rostered players.

## Setup Instructions

### 0. Apply for Fantasy Sports API access (Yahoo now gates this)

> **Status for this repo: granted 2026-09-15.** Kept here because a new app still has to
> go through it, and because the failure mode is otherwise baffling.

As of 2026, Yahoo requires a separate approval step before the Fantasy Sports API works for
any app — the old "just check the Fantasy Sports box in the app console" flow is no longer
sufficient. `developer.yahoo.com/fantasysports/guide` now redirects to
`sports.yahoo.com/developer`, a new portal where you submit a product description, what data
you need, and expected usage; Yahoo's Fantasy Sports team reviews it before API calls succeed.

Apply at https://sports.yahoo.com/developer/access/. Until approved, every call — even the
basic `users;games` endpoint — fails with `"This application is not authorized to perform
this action."`, regardless of how fresh your OAuth token is. Re-authenticating does not fix
this; only approval does. Access is read-only by default.

### 1. Create a Yahoo App

1. Go to https://developer.yahoo.com/apps/create/
2. Sign in with your Yahoo account
3. Fill out the form:
   - **Application Name**: "Fantasy Hockey Analyzer" (or whatever you want)
   - **Application Type**: Web Application
   - **Callback Domain**: `localhost`
   - **API Permissions**: Check "Fantasy Sports"
4. Click **Create App**
5. You'll see your **Client ID (Consumer Key)** and **Client Secret (Consumer Secret)**

### 2. Create oauth2.json

Copy the example file and fill in your credentials:

```bash
cp oauth2.json.example oauth2.json
```

Edit `oauth2.json` with your credentials:

```json
{
  "consumer_key": "YOUR_CLIENT_ID_HERE",
  "consumer_secret": "YOUR_CLIENT_SECRET_HERE"
}
```

### 3. First Run - OAuth Flow

The first time you run `python main.py pickups` with Yahoo enabled:

1. A browser window will open asking you to authorize the app
2. Click "Agree" to allow access to your Yahoo Fantasy data
3. You'll be redirected to a localhost URL that shows a code
4. The app will automatically save the access token for future use

### 4. Security

**IMPORTANT**: The `oauth2.json` file is already in `.gitignore` to prevent accidentally committing your credentials.

Never share or commit:
- `oauth2.json` (your credentials)
- Any generated token files

## Troubleshooting

### `RuntimeError: ... "This application is not authorized to perform this action."`

This is not a token or scope problem — a freshly re-authenticated token fails identically.
It means the app hasn't been approved under Yahoo's access-application process (see step 0
above). Apply at https://sports.yahoo.com/developer/access/ and wait for approval; deleting
`oauth2.json`'s token fields and re-running the OAuth flow will not help.

### "No such file or directory: oauth2.json"

This is normal if you haven't set up Yahoo API. The app will continue without roster filtering.

To enable Yahoo API, follow the setup instructions above.

### OAuth token expired

If you see authentication errors, delete any token cache files and re-run:

```bash
rm -f oauth2*.json.token
python main.py pickups
```

This will trigger a new OAuth flow.

### `403 "You are not allowed to view this page because you are not in this league."`

A different failure from the one above, and it means the opposite: the app is authorized, the
league key is wrong. Almost always a bare `nhl.l.<id>` key. `nhl` is an alias for the **current**
game, which rolls every September (465 = 2025, 477 = 2026), so `nhl.l.33072` stopped meaning our
league the moment Yahoo created the 2026 game — it started naming league 33072 in *that* game,
which belongs to strangers.

Nothing is hardcoded now. `yahooAPI.getLeague()` asks Yahoo which season is live and resolves
our league by **name** (`yahooAPI.LEAGUE_NAME`), because the numeric id changes every year:

| Season | League key |
|---|---|
| 2024 | `453.l.27273` |
| 2025 | `465.l.33072` |
| 2026 | `477.l.12419` |

To point this at a different league, change `LEAGUE_NAME` in `src/yahooAPI.py`, or pass
`league_id=` to `getLeague()` / `getLeagueForYear()` to bypass resolution entirely.

### Two leagues, on purpose

`getLeague()` returns the **live** league (where you draft and play). `getRosterLeague()`
returns the **previous** season's, and that is where your current roster lives — from the day
Yahoo creates next season's league until its draft, every roster in it is empty. Keeper analysis
reads the roster-source league; pickup filtering reads the live one.

### Checking access

```powershell
.\.venv\Scripts\python.exe scripts\check_yahoo_access.py
```

Stages escalate, so the first failure names the broken layer.

## References

- [yahoo-oauth documentation](https://github.com/josuebrunel/yahoo-oauth)
- [yahoo-fantasy-api documentation](https://yahoo-fantasy-api.readthedocs.io/)
- [Yahoo Developer Network](https://developer.yahoo.com/)
