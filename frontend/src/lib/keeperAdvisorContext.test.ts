import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import type { AdvisorContext, TurnClassification } from '../types/keeperAdvisor';
import {
  bestScenario,
  buildGroundingContext,
  loadAdvisorContext,
  rosterIndex,
} from './keeperAdvisorContext';


const context: AdvisorContext = {
  schema_version: 1,
  context_id: 'ctx-1',
  generated_at: '2026-07-17T12:00:00Z',
  season: '2026-27',
  league: { team_count: 10, keeper_count: 4 },
  official_top_four: [1, 2, 3, 4],
  roster: [1, 2, 3, 4, 5].map((id) => ({
    player_id: id,
    yahoo_player_id: `y${id}`,
    yahoo_name: `Player ${id}`,
    full_name: `Player ${id}`,
    position: 'C',
    match_status: 'matched',
    excluded_reason: null,
    is_recommended: id <= 4,
    keeper_rank: id <= 4 ? id : null,
    raw_keeper_value: 100 - id * 10,
    projected_total: 250 - id * 5,
    age: 20 + id,
    history: [{ season: 2024, fpPerGame: 3 - id / 10 }],
  })),
  scenario_data: {
    sets: [
      {
        player_ids: [1, 2, 3, 4],
        players: [],
        total_model_value: 300,
        total_net_keeper_value: 100,
      },
      {
        player_ids: [1, 2, 3, 5],
        players: [],
        total_model_value: 288,
        total_net_keeper_value: 88,
      },
    ],
  },
};


test('loadAdvisorContext accepts the exact server artifact', () => {
  const directory = mkdtempSync(join(tmpdir(), 'keeper-advisor-'));
  const path = join(directory, 'context.json');
  writeFileSync(path, JSON.stringify(context), 'utf8');
  assert.deepEqual(loadAdvisorContext(path), context);
});


test('bestScenario applies locked and excluded ids deterministically', () => {
  assert.deepEqual(bestScenario(context, [5], []), context.scenario_data.sets[1]);
  assert.deepEqual(bestScenario(context, [], [4]), context.scenario_data.sets[1]);
  assert.equal(bestScenario(context, [4, 5], []), null);
});


test('grounding sends a compact roster index plus only referenced dossiers', () => {
  const classification: TurnClassification = {
    objective: 'balanced',
    needs_current_research: false,
    referenced_player_ids: [5],
    locked_player_ids: [5],
    excluded_player_ids: [],
    conversation_summary: 'Player 5 is locked.',
  };
  const grounding = buildGroundingContext(context, classification);
  assert.equal(grounding.roster_index.length, 5);
  assert.deepEqual(
    grounding.player_dossiers.map((row) => row.player_id),
    [1, 2, 3, 4, 5],
  );
  assert.deepEqual(grounding.scenario?.player_ids, [1, 2, 3, 5]);
  assert.equal('scenario_data' in grounding, false);
});


test('roster index excludes history and factor payloads', () => {
  const index = rosterIndex(context);
  assert.equal('history' in index[0], false);
  assert.equal(index[0].player_id, 1);
  assert.equal(index[0].raw_keeper_value, 90);
});
