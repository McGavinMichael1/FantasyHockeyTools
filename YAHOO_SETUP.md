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

### Wrong league ID

The code currently hardcodes league `nhl.l.33072` in [src/yahooAPI.py:12](src/yahooAPI.py#L12).

To use a different league:
1. Find your league ID from the Yahoo Fantasy URL (e.g., `https://hockey.fantasysports.yahoo.com/hockey/12345` → ID is `12345`)
2. Edit `src/yahooAPI.py` line 12: `lg = gm.to_league('nhl.l.YOUR_LEAGUE_ID')`

## References

- [yahoo-oauth documentation](https://github.com/josuebrunel/yahoo-oauth)
- [yahoo-fantasy-api documentation](https://yahoo-fantasy-api.readthedocs.io/)
- [Yahoo Developer Network](https://developer.yahoo.com/)
