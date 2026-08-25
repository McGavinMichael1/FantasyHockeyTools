"""The Python half of the cross-language best-available contract.

`tests/fixtures/best_available_cases.json` is run against BOTH implementations:
this one and `frontend/src/lib/bestAvailable.ts`. The live draft board cannot
call Python -- it has to work on draft day with nothing running behind it -- so
the rule genuinely exists twice. This file and its TypeScript twin are what stop
the two copies drifting the way liveDraft.ts and keeper.py nearly did.

If you change the rule, change it in both places; the fixture will tell you if
you only changed one.
"""

import json
import os

import pandas as pd
import pytest

from src import keeper, mockDraft


FIXTURE_PATH = os.path.join(os.path.dirname(__file__), 'fixtures',
                            'best_available_cases.json')


def _fixture() -> dict:
    with open(FIXTURE_PATH, encoding='utf-8') as handle:
        return json.load(handle)


FIXTURE = _fixture()


def test_the_fixture_pins_the_live_league_constants():
    """A slot change in keeper.py must not leave the frontend on stale numbers.

    The TypeScript side asserts its fallback constants against this same block,
    so failing here is the signal to update the fixture AND the TS fallback --
    not to loosen the assertion.
    """
    rules = FIXTURE['rules']

    assert keeper.STARTING_SLOTS == rules['starting_slots']
    assert mockDraft.MAX_BY_POSITION == rules['max_by_position']


@pytest.mark.parametrize(
    'case', FIXTURE['cases'], ids=[c['name'] for c in FIXTURE['cases']])
def test_best_available_matches_the_shared_fixture(case):
    board = pd.DataFrame(case['board'])

    choice = mockDraft.best_available(
        board,
        set(case['taken']),
        dict(case['counts']),
        case['kept_counts'],
        case['picks_left'],
    )

    chosen_id = None if choice is None else int(choice['playerId'])
    assert chosen_id == case['expected_playerId'], case.get('why', '')
