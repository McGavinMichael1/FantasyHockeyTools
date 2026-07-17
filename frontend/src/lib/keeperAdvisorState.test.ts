import assert from 'node:assert/strict';
import test from 'node:test';

import type {
  KeeperAdvisorResponse,
  StoredAdvisorConversation,
  StoredAdvisorTurn,
} from '../types/keeperAdvisor';
import {
  appendTurn,
  emptyConversation,
  listStaleConversations,
  loadConversation,
  requestMessages,
  saveConversation,
  STORAGE_PREFIX,
} from './keeperAdvisorState';


class MemoryStorage {
  private store = new Map<string, string>();
  get length() { return this.store.size; }
  getItem(key: string) { return this.store.get(key) ?? null; }
  setItem(key: string, value: string) { this.store.set(key, value); }
  removeItem(key: string) { this.store.delete(key); }
  key(index: number) { return [...this.store.keys()][index] ?? null; }
}


const reply: KeeperAdvisorResponse = {
  stance: 'agrees',
  objective: 'balanced',
  answer: 'Keep 1-4.',
  model_view: 'Model keeps 1-4.',
  recommendation: 'Keep 1-4.',
  tradeoff: { out_player_id: null, in_player_id: null, projected_keeper_value_cost: null },
  qualitative_factors: [],
  uncertainty: [],
  research: { used: false, current_information_verified: null, as_of: null, sources: [] },
};


function userTurn(content: string): StoredAdvisorTurn {
  return { id: crypto.randomUUID(), role: 'user', content, created_at: '2026-07-17T12:00:00Z' };
}


test('a saved conversation round-trips', () => {
  const storage = new MemoryStorage();
  const conversation = appendTurn(
    emptyConversation('ctx-1', '2026-27'),
    userTurn('Who should I keep?'),
  );
  saveConversation(storage, conversation);
  assert.deepEqual(loadConversation(storage, 'ctx-1', '2026-27'), conversation);
});


test('malformed JSON returns a fresh empty conversation', () => {
  const storage = new MemoryStorage();
  storage.setItem(`${STORAGE_PREFIX}ctx-1`, 'not json');
  const conversation = loadConversation(storage, 'ctx-1', '2026-27');
  assert.deepEqual(conversation, emptyConversation('ctx-1', '2026-27'));
});


test('a record for a different context id is ignored on load', () => {
  const storage = new MemoryStorage();
  saveConversation(storage, {
    ...emptyConversation('ctx-1', '2026-27'),
    context_id: 'ctx-other',
  });
  assert.deepEqual(
    loadConversation(storage, 'ctx-1', '2026-27'),
    emptyConversation('ctx-1', '2026-27'),
  );
});


test('stale conversations are listed newest-first and exclude the current id', () => {
  const storage = new MemoryStorage();
  saveConversation(storage, {
    ...emptyConversation('ctx-current', '2026-27'), updated_at: '2026-07-17T12:00:00Z',
  });
  saveConversation(storage, {
    ...emptyConversation('ctx-old', '2025-26'), updated_at: '2026-07-10T12:00:00Z',
  });
  saveConversation(storage, {
    ...emptyConversation('ctx-older', '2024-25'), updated_at: '2026-07-01T12:00:00Z',
  });
  storage.setItem(`${STORAGE_PREFIX}ctx-bad`, 'not json');

  const stale = listStaleConversations(storage, 'ctx-current');
  assert.deepEqual(stale.map((entry) => entry.context_id), ['ctx-old', 'ctx-older']);
});


test('15 turns produce the last 12 request messages in order', () => {
  let conversation: StoredAdvisorConversation = emptyConversation('ctx-1', '2026-27');
  for (let index = 0; index < 15; index += 1) {
    conversation = appendTurn(conversation, userTurn(`message-${index}`));
  }
  const messages = requestMessages(conversation);
  assert.equal(messages.length, 12);
  assert.equal(messages[0].content, 'message-3');
  assert.equal(messages[11].content, 'message-14');
});


test('failed turns are excluded from the request payload', () => {
  let conversation = appendTurn(emptyConversation('ctx-1', '2026-27'), userTurn('good'));
  conversation = appendTurn(conversation, {
    ...userTurn('failed'), failed: true,
  });
  const messages = requestMessages(conversation);
  assert.deepEqual(messages.map((message) => message.content), ['good']);
});


test('appendTurn preserves the independent summary and updates the timestamp', () => {
  const start = appendTurn(
    emptyConversation('ctx-1', '2026-27'), userTurn('Who?'), 'first summary',
  );
  assert.equal(start.conversation_summary, 'first summary');
  const next = appendTurn(start, {
    id: crypto.randomUUID(), role: 'assistant', content: 'Keep 1-4.',
    reply, created_at: '2026-07-17T12:05:00Z',
  });
  assert.equal(next.conversation_summary, 'first summary');
  const kept = appendTurn(next, userTurn('Again?'), 'second summary');
  assert.equal(kept.conversation_summary, 'second summary');
  assert.equal(kept.turns.length, 3);
});
