import assert from 'node:assert/strict';
import test from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import type { KeeperAdvisorResponse } from '../../types/keeperAdvisor';
import { KeeperAdvisorMessage } from './KeeperAdvisorMessage';


const playerNames = { 4: 'Player 4', 5: 'Player 5' };

const divergingResearched: KeeperAdvisorResponse = {
  stance: 'diverges',
  objective: 'multi_year',
  answer: 'Keep Player 5 for the upside.',
  model_view: 'The model keeps Player 4.',
  recommendation: 'Swap Player 5 in for Player 4.',
  tradeoff: {
    out_player_id: 4,
    in_player_id: 5,
    projected_keeper_value_cost: 12,
  },
  qualitative_factors: ['Age and trajectory'],
  uncertainty: ['Multi-year upside is qualitative'],
  research: {
    used: true,
    current_information_verified: true,
    as_of: '2026-07-17T12:00:00.000Z',
    sources: [{
      title: 'Player news',
      url: 'https://example.test/player-news',
      published_at: '2026-07-16',
      retrieved_at: '2026-07-17T12:00:00.000Z',
    }],
  },
};

const localAgreeing: KeeperAdvisorResponse = {
  stance: 'agrees',
  objective: 'balanced',
  answer: 'The model keepers are correct.',
  model_view: 'The model keeps 1-4.',
  recommendation: 'Keep the model four.',
  tradeoff: { out_player_id: null, in_player_id: null, projected_keeper_value_cost: null },
  qualitative_factors: [],
  uncertainty: [],
  research: { used: false, current_information_verified: null, as_of: null, sources: [] },
};


test('a diverging researched reply renders badges, tradeoff, and sources', () => {
  const html = renderToStaticMarkup(
    createElement(KeeperAdvisorMessage, { reply: divergingResearched, playerNames }),
  );
  assert.match(html, /Diverges from model/);
  assert.match(html, /Multi-year/);
  assert.match(html, /Player 4[\s\S]*Player 5/);
  assert.match(html, /12\.000 keeper-value points/);
  assert.match(html, /https:\/\/example\.test\/player-news/);
  assert.match(html, /Current information verified/);
});


test('a local agreeing reply says no live research and lists no sources', () => {
  const html = renderToStaticMarkup(
    createElement(KeeperAdvisorMessage, { reply: localAgreeing, playerNames }),
  );
  assert.match(html, /Model agrees/);
  assert.match(html, /No live research needed/);
  assert.equal(html.includes('example.test'), false);
});
