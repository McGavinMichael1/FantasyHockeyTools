from scripts.publish_draft_data import public_payload


def test_public_payload_keeps_only_the_draft_board():
    full = {
        'draft': [{'id': 1}],
        'draft_replacement_ranks': {'C': 20},
        'draft_roster_rules': {'util_slots': 1},
        'generated_at': '2026-09-18T00:00:00',
        'pickups': [{'id': 2}],
        'cooling': [{'id': 3}],
        'keeper': {'advisor_roster': [{'name': 'Mine'}]},
        'some_future_private_section': {'secret': True},
    }
    out = public_payload(full)
    assert set(out) == {'draft', 'draft_replacement_ranks', 'draft_roster_rules',
                        'generated_at', 'pickups', 'cooling', 'keeper'}
    assert out['draft'] == [{'id': 1}]
    assert out['pickups'] == [] and out['cooling'] == [] and out['keeper'] is None
