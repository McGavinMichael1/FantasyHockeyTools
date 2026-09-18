"""Write the league-shareable slice of frontend_data.json for the hosted draft board.

The full export holds the owner's private edge (pickup/cooling recommendations,
keeper roster and scenarios). League-mates get the draft board only, so this is
a WHITELIST: a section added to api_export.py later stays private by default.

Reads  data/processed/frontend_data.json   (run api_export.py first)
Writes frontend/public/frontend_data.json   (gitignored; deploy_draft_board.ps1
                                             deletes it after the build)
"""
import json
import os
import sys

SOURCE = os.path.join('data', 'processed', 'frontend_data.json')
TARGET = os.path.join('frontend', 'public', 'frontend_data.json')

PUBLIC_KEYS = ('draft', 'draft_replacement_ranks', 'draft_roster_rules', 'generated_at')


def public_payload(data: dict) -> dict:
    """Draft-board sections only; the private sections are emptied, not omitted,
    so the page's existing shape checks still pass."""
    out = {key: data[key] for key in PUBLIC_KEYS if key in data}
    out.update(pickups=[], cooling=[], keeper=None)
    return out


def main() -> None:
    if not os.path.exists(SOURCE):
        sys.exit(f"{SOURCE} not found -- run api_export.py first")
    with open(SOURCE, encoding='utf-8') as f:
        data = json.load(f)
    if not data.get('draft'):
        sys.exit(f"{SOURCE} has no draft section -- run main.py draft, then api_export.py")
    with open(TARGET, 'w', encoding='utf-8') as f:
        json.dump(public_payload(data), f, ensure_ascii=False)
    print(f"wrote {TARGET} ({len(data['draft'])} draft players)")


if __name__ == '__main__':
    main()
