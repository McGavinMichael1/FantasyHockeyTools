# Build and publish the league-hosted draft board (Cloudflare Pages).
#
#   .\scripts\deploy_draft_board.ps1            # build + deploy
#   .\scripts\deploy_draft_board.ps1 -BuildOnly # build frontend\out only, for a local check
#
# Refresh data first with api_export.py. Only the draft slice is published
# (scripts\publish_draft_data.py whitelists it); access is gated by Cloudflare
# Access -- see the fht-operations skill for the one-time setup.
param([switch]$BuildOnly)
$ErrorActionPreference = 'Stop'

$root = Split-Path $PSScriptRoot -Parent
$publicData = Join-Path $root 'frontend\public\frontend_data.json'

Push-Location $root
try {
    & .\.venv\Scripts\python.exe scripts\publish_draft_data.py
    if ($LASTEXITCODE -ne 0) { throw 'publish_draft_data.py failed' }

    Set-Location frontend
    $env:NEXT_PUBLIC_FHT_DRAFT_ONLY = '1'
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'next build failed' }

    if (-not $BuildOnly) {
        npx wrangler pages deploy out --project-name fht-draft-board --branch main
        if ($LASTEXITCODE -ne 0) { throw 'wrangler deploy failed' }
    }
}
finally {
    Remove-Item Env:NEXT_PUBLIC_FHT_DRAFT_ONLY -ErrorAction SilentlyContinue
    # frontend\out keeps its own copy; this one must not linger in public\.
    Remove-Item $publicData -ErrorAction SilentlyContinue
    Pop-Location
}
