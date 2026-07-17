import assert from 'node:assert/strict';
import test from 'node:test';

import type {
  AdvisorContext,
  AdvisorResearch,
  ProviderAnswerDraft,
  TurnClassification,
} from '../../../types/keeperAdvisor';
import type { KeeperAdvisorProvider } from '../../../lib/anthropicKeeperAdvisor';
import { isAdvisorResponse } from '../../../lib/keeperAdvisorSchema';
import { createKeeperChatPost } from './route';


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
  })),
  scenario_data: {
    sets: [
      {
        player_ids: [1, 2, 3, 4],
        players: [],
        total_model_value: 300,
        total_net_keeper_value: 100,
      },
    ],
  },
};

const unusedResearch: AdvisorResearch = {
  used: false,
  current_information_verified: null,
  as_of: null,
  sources: [],
};

const classification: TurnClassification = {
  objective: 'balanced',
  needs_current_research: false,
  referenced_player_ids: [],
  locked_player_ids: [],
  excluded_player_ids: [],
  conversation_summary: 'Local comparison.',
};

const draft: ProviderAnswerDraft = {
  stance: 'agrees',
  objective: 'balanced',
  answer: 'Answer text.',
  model_view: 'Model view text.',
  recommendation: 'Recommendation text.',
  tradeoff: {
    out_player_id: null,
    in_player_id: null,
    projected_keeper_value_cost: null,
  },
  qualitative_factors: [],
  uncertainty: [],
  research: unusedResearch,
  recommended_player_ids: [1, 2, 3, 4],
};

const workingProvider: KeeperAdvisorProvider = {
  async classify() { return classification; },
  async answer() { return { draft, research: unusedResearch }; },
};

const configured = {
  ANTHROPIC_API_KEY: 'test-key',
  KEEPER_ADVISOR_MODEL: 'claude-test-model',
};


function post(body: BodyInit) {
  return new Request('http://localhost/api/keeper-chat', { method: 'POST', body });
}


function validBody(contextId = 'ctx-1') {
  return JSON.stringify({
    context_id: contextId,
    messages: [{ role: 'user', content: 'Who should I keep?' }],
    conversation_summary: null,
  });
}


function handler(overrides: Record<string, unknown> = {}) {
  return createKeeperChatPost({
    loadContext: () => context,
    providerFactory: () => workingProvider,
    environment: configured,
    ...overrides,
  });
}


test('malformed JSON is rejected as invalid_request', async () => {
  const response = await handler()(post('not json'));
  assert.equal(response.status, 400);
  const body = await response.json();
  assert.equal(body.error.code, 'invalid_request');
  assert.equal(response.headers.get('cache-control'), 'no-store');
});


test('a request whose final message is not from the user is invalid', async () => {
  const response = await handler()(post(JSON.stringify({
    context_id: 'ctx-1',
    messages: [
      { role: 'user', content: 'Who should I keep?' },
      { role: 'assistant', content: 'The model keeps 1-4.' },
    ],
    conversation_summary: null,
  })));
  assert.equal(response.status, 400);
  assert.equal((await response.json()).error.code, 'invalid_request');
});


test('a missing context file maps to 503 missing_context', async () => {
  const response = await handler({
    loadContext: () => { throw new Error('ENOENT: no such file'); },
  })(post(validBody()));
  assert.equal(response.status, 503);
  assert.equal((await response.json()).error.code, 'missing_context');
});


test('a stale context id maps to 409 with the current id', async () => {
  const response = await handler()(post(validBody('ctx-outdated')));
  assert.equal(response.status, 409);
  const body = await response.json();
  assert.equal(body.error.code, 'stale_context');
  assert.equal(body.error.current_context_id, 'ctx-1');
});


test('missing key or model configuration maps to 503 without leaking values', async () => {
  for (const environment of [
    {},
    { ANTHROPIC_API_KEY: 'test-key' },
    { KEEPER_ADVISOR_MODEL: 'claude-test-model' },
  ]) {
    const response = await handler({ environment })(post(validBody()));
    assert.equal(response.status, 503);
    const text = await response.text();
    assert.equal(JSON.parse(text).error.code, 'missing_configuration');
    assert.equal(text.includes('test-key'), false);
  }
});


test('a valid request returns a validated success payload', async () => {
  const response = await handler()(post(validBody()));
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('cache-control'), 'no-store');
  const body = await response.json();
  assert.equal(isAdvisorResponse(body.reply), true);
  assert.equal(typeof body.conversation_summary, 'string');
});


test('provider failures map to 502 provider_error', async () => {
  const failing: KeeperAdvisorProvider = {
    async classify() { throw new Error('boom'); },
    async answer() { throw new Error('boom'); },
  };
  const response = await handler({ providerFactory: () => failing })(post(validBody()));
  assert.equal(response.status, 502);
  assert.equal((await response.json()).error.code, 'provider_error');
});
