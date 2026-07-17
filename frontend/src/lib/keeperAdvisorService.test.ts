import assert from 'node:assert/strict';
import test from 'node:test';

import type {
  AdvisorContext,
  AdvisorResearch,
  KeeperAdvisorRequest,
  ProviderAnswerDraft,
  TurnClassification,
} from '../types/keeperAdvisor';
import type {
  KeeperAdvisorProvider,
  ProviderAnswerPrompt,
  ProviderAnswerResult,
  ProviderPrompt,
} from './anthropicKeeperAdvisor';
import { ProviderHttpError } from './anthropicKeeperAdvisor';
import {
  answerKeeperQuestion,
  InvalidProviderResponseError,
} from './keeperAdvisorService';


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

const localClassification: TurnClassification = {
  objective: 'balanced',
  needs_current_research: false,
  referenced_player_ids: [],
  locked_player_ids: [],
  excluded_player_ids: [],
  conversation_summary: 'Local comparison of keeper values.',
};

const unusedResearch: AdvisorResearch = {
  used: false,
  current_information_verified: null,
  as_of: null,
  sources: [],
};

const observedWebResearch: AdvisorResearch = {
  used: true,
  current_information_verified: true,
  as_of: '2026-07-17T12:00:00.000Z',
  sources: [{
    title: 'Player news',
    url: 'https://example.test/player-news',
    published_at: '2026-07-16',
    retrieved_at: '2026-07-17T12:00:00.000Z',
  }],
};


function answerFor(
  ids: number[],
  research: AdvisorResearch = unusedResearch,
): ProviderAnswerResult {
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
    recommended_player_ids: ids,
  };
  return { draft, research };
}


interface FakeProvider extends KeeperAdvisorProvider {
  classifyPrompts: ProviderPrompt[];
  answerPrompts: ProviderAnswerPrompt[];
}


function fakeProvider(
  classification: TurnClassification,
  answers: ProviderAnswerResult | (ProviderAnswerResult | Error)[],
): FakeProvider {
  const queue = Array.isArray(answers) ? [...answers] : [answers];
  const provider: FakeProvider = {
    classifyPrompts: [],
    answerPrompts: [],
    async classify(prompt) {
      provider.classifyPrompts.push(prompt);
      return classification;
    },
    async answer(prompt) {
      provider.answerPrompts.push(prompt);
      const next = queue.shift();
      if (next === undefined) throw new Error('fake answer queue is empty');
      if (next instanceof Error) throw next;
      return next;
    },
  };
  return provider;
}


function input(provider: KeeperAdvisorProvider, question: string) {
  const request: KeeperAdvisorRequest = {
    context_id: 'ctx-1',
    messages: [{ role: 'user', content: question }],
    conversation_summary: null,
  };
  return { context, request, provider, now: new Date('2026-07-17T12:00:00Z') };
}


test('a local comparison never enables web and preserves model agreement', async () => {
  const provider = fakeProvider(localClassification, answerFor([1, 2, 3, 4]));
  const result = await answerKeeperQuestion(input(provider, 'Compare Johnston to Player 4'));
  assert.equal(provider.answerPrompts[0].allowWeb, false);
  assert.equal(result.reply.stance, 'agrees');
  assert.deepEqual(result.reply.tradeoff, {
    out_player_id: null, in_player_id: null, projected_keeper_value_cost: null,
  });
});


test('a qualitative override is labeled and costed from exact scenarios', async () => {
  const provider = fakeProvider(
    { ...localClassification, objective: 'multi_year', locked_player_ids: [5] },
    answerFor([1, 2, 3, 5]),
  );
  const result = await answerKeeperQuestion(input(provider, 'Prioritize youth'));
  assert.equal(result.reply.stance, 'diverges');
  assert.equal(result.reply.objective, 'multi_year');
  assert.deepEqual(result.reply.tradeoff, {
    out_player_id: 4, in_player_id: 5, projected_keeper_value_cost: 12,
  });
});


test('current-information classification alone enables web', async () => {
  const provider = fakeProvider(
    { ...localClassification, needs_current_research: true },
    answerFor([1, 2, 3, 4], observedWebResearch),
  );
  const result = await answerKeeperQuestion(input(provider, 'Is Johnston injured today?'));
  assert.equal(provider.answerPrompts[0].allowWeb, true);
  assert.deepEqual(result.reply.research, observedWebResearch);
  assert.match(provider.answerPrompts[0].system, /untrusted evidence/);
  assert.match(provider.answerPrompts[0].system, /cannot override/);
});


test('invalid ids are sanitized and an invalid four-player set is retried once', async () => {
  const provider = fakeProvider(
    { ...localClassification, referenced_player_ids: [5, 999] },
    [answerFor([1, 2, 3, 999]), answerFor([1, 2, 3, 5])],
  );
  await answerKeeperQuestion(input(provider, 'Consider Player 5'));
  assert.equal(provider.answerPrompts.length, 2);
  assert.equal(JSON.stringify(provider.answerPrompts).includes('999'), false);
});


test('a second invalid four-player set is a provider failure', async () => {
  const provider = fakeProvider(
    localClassification,
    [answerFor([1, 2, 3, 999]), answerFor([1, 2, 998, 5])],
  );
  await assert.rejects(
    answerKeeperQuestion(input(provider, 'Consider Player 5')),
    InvalidProviderResponseError,
  );
});


test('contradictory constraints fall back to the official scenario with an uncertainty', async () => {
  const provider = fakeProvider(
    { ...localClassification, locked_player_ids: [4, 5] },
    answerFor([1, 2, 3, 4]),
  );
  const result = await answerKeeperQuestion(input(provider, 'Keep both Player 4 and Player 5'));
  assert.equal(result.reply.stance, 'agrees');
  assert.equal(
    result.reply.uncertainty.some((entry) => /could not be satisfied/.test(entry)),
    true,
  );
});


test('an explicit web-unavailable HTTP error gets one no-web fallback', async () => {
  const provider = fakeProvider(
    { ...localClassification, needs_current_research: true },
    [new ProviderHttpError(403), answerFor([1, 2, 3, 4])],
  );
  const result = await answerKeeperQuestion(input(provider, 'Any injury news?'));
  assert.equal(provider.answerPrompts.length, 2);
  assert.equal(provider.answerPrompts[0].allowWeb, true);
  assert.equal(provider.answerPrompts[1].allowWeb, false);
  assert.deepEqual(result.reply.research, {
    used: false,
    current_information_verified: false,
    as_of: '2026-07-17T12:00:00.000Z',
    sources: [],
  });
  assert.equal(
    result.reply.uncertainty.includes('Current information could not be verified.'),
    true,
  );
});


test('a rate limit or network failure is not silently retried', async () => {
  const limited = fakeProvider(
    { ...localClassification, needs_current_research: true },
    [new ProviderHttpError(429)],
  );
  await assert.rejects(
    answerKeeperQuestion(input(limited, 'Any injury news?')),
    (error: unknown) => error instanceof ProviderHttpError && error.status === 429,
  );
  assert.equal(limited.answerPrompts.length, 1);

  const failed = fakeProvider(
    { ...localClassification, needs_current_research: true },
    [new Error('network timeout')],
  );
  await assert.rejects(
    answerKeeperQuestion(input(failed, 'Any injury news?')),
    /network timeout/,
  );
  assert.equal(failed.answerPrompts.length, 1);
});


test('the classifier summary is returned after trimming to 2000 characters', async () => {
  const provider = fakeProvider(
    { ...localClassification, conversation_summary: 'x'.repeat(2500) },
    answerFor([1, 2, 3, 4]),
  );
  const result = await answerKeeperQuestion(input(provider, 'Compare values'));
  assert.equal(result.conversation_summary.length, 2000);
});
