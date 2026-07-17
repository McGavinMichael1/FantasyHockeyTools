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


function scenarioPlayers(playerIds: number[]) {
  return playerIds.map((player_id, index) => ({
    player_id,
    assigned_round: index + 1,
    pick_cost: 10 - index,
    raw_keeper_value: 100 - index * 10,
    net_keeper_value: 90 - index * 10,
  }));
}


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
        players: scenarioPlayers([1, 2, 3, 4]),
        total_model_value: 300,
        total_net_keeper_value: 100,
      },
      {
        player_ids: [1, 2, 3, 5],
        players: scenarioPlayers([1, 2, 3, 5]),
        total_model_value: 288,
        total_net_keeper_value: 88,
      },
    ],
  },
};


function writeArtifact(value: unknown) {
  const directory = mkdtempSync(join(tmpdir(), 'keeper-advisor-'));
  const path = join(directory, 'context.json');
  writeFileSync(path, JSON.stringify(value), 'utf8');
  return path;
}


test('loadAdvisorContext accepts the exact server artifact', () => {
  assert.deepEqual(loadAdvisorContext(writeArtifact(context)), context);
});


test('loadAdvisorContext rejects duplicate and non-numeric top-four IDs', () => {
  const duplicateIds = structuredClone(context);
  duplicateIds.official_top_four = [1, 2, 3, 3];
  const nonNumericIds = structuredClone(context);
  nonNumericIds.official_top_four = [1, 2, 3, '4'] as unknown as number[];

  for (const artifact of [duplicateIds, nonNumericIds]) {
    assert.throws(
      () => loadAdvisorContext(writeArtifact(artifact)),
      { message: 'keeper advisor context has an unsupported or malformed schema' },
    );
  }
});


test('loadAdvisorContext rejects a malformed roster player', () => {
  const missingFields = structuredClone(context) as unknown as { roster: unknown[] };
  missingFields.roster[0] = { player_id: 1, yahoo_name: 'Player 1' };
  const nonRecord = structuredClone(context) as unknown as { roster: unknown[] };
  nonRecord.roster[0] = ['not', 'a', 'player'];

  for (const artifact of [missingFields, nonRecord]) {
    assert.throws(
      () => loadAdvisorContext(writeArtifact(artifact)),
      { message: 'keeper advisor context has an unsupported or malformed schema' },
    );
  }
});


test('loadAdvisorContext rejects a malformed scenario set', () => {
  const invalidPlayerIds = structuredClone(context) as unknown as {
    scenario_data: { sets: unknown[] };
  };
  invalidPlayerIds.scenario_data.sets[0] = {
    player_ids: [1, 2, 3, '4'],
    players: [],
    total_model_value: 300,
    total_net_keeper_value: 100,
  };
  const invalidScenarioPlayer = structuredClone(context) as unknown as {
    scenario_data: { sets: Array<Record<string, unknown>> };
  };
  invalidScenarioPlayer.scenario_data.sets[0].players = [{ player_id: 1 }];
  const invalidTotal = structuredClone(context) as unknown as {
    scenario_data: { sets: Array<Record<string, unknown>> };
  };
  invalidTotal.scenario_data.sets[0].total_model_value = null;

  for (const artifact of [invalidPlayerIds, invalidScenarioPlayer, invalidTotal]) {
    assert.throws(
      () => loadAdvisorContext(writeArtifact(artifact)),
      { message: 'keeper advisor context has an unsupported or malformed schema' },
    );
  }
});


test('loadAdvisorContext rejects invalid four-player scenario invariants', () => {
  const wrongCardinality = structuredClone(context) as unknown as {
    scenario_data: { sets: Array<{ player_ids: unknown }> };
  };
  wrongCardinality.scenario_data.sets[0].player_ids = [1, 2, 3];
  const duplicateIds = structuredClone(context) as unknown as {
    scenario_data: { sets: Array<{ player_ids: unknown }> };
  };
  duplicateIds.scenario_data.sets[0].player_ids = [1, 2, 3, 3];
  const mismatchedPlayers = structuredClone(context) as unknown as {
    scenario_data: { sets: Array<{ players: Array<{ player_id: number }> }> };
  };
  mismatchedPlayers.scenario_data.sets[1].players[3].player_id = 4;

  for (const artifact of [wrongCardinality, duplicateIds, mismatchedPlayers]) {
    assert.throws(
      () => loadAdvisorContext(writeArtifact(artifact)),
      { message: 'keeper advisor context has an unsupported or malformed schema' },
    );
  }
});


test('loadAdvisorContext rejects a malformed league', () => {
  const malformed = structuredClone(context) as unknown as { league: unknown };
  malformed.league = ['not', 'a', 'record'];

  assert.throws(
    () => loadAdvisorContext(writeArtifact(malformed)),
    { message: 'keeper advisor context has an unsupported or malformed schema' },
  );
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
