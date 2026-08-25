import assert from 'node:assert/strict';
import test from 'node:test';
import {
  DEFAULT_PICK_BUDGET,
  loadSetup,
  saveSetup,
  type DraftSetup,
} from './draftSetup';

function storageWith(entries: Record<string, string> = {}): Storage {
  const map = new Map<string, string>(Object.entries(entries));
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    removeItem: (k: string) => void map.delete(k),
    clear: () => map.clear(),
    key: () => null,
    length: 0,
  } as unknown as Storage;
}

test('an unconfigured board starts with no keepers and the default budget', () => {
  assert.deepEqual(loadSetup(storageWith()), {
    keeperIds: [],
    pickBudget: DEFAULT_PICK_BUDGET,
  });
});

test('setup survives a round trip', () => {
  const storage = storageWith();
  const setup: DraftSetup = { keeperIds: [3, 7], pickBudget: 12 };
  saveSetup(setup, storage);
  assert.deepEqual(loadSetup(storage), setup);
});

test('keeping nobody is remembered rather than reset to the default', () => {
  // "I am keeping no one" is a real answer, and re-reading it as "unconfigured"
  // would silently re-apply keepers the owner deliberately cleared.
  const storage = storageWith();
  saveSetup({ keeperIds: [], pickBudget: 18 }, storage);
  assert.equal(loadSetup(storage).pickBudget, 18);
});

test('corrupt setup falls back to the defaults rather than throwing', () => {
  assert.deepEqual(loadSetup(storageWith({ 'fht.draftSetup.v1': 'not json' })), {
    keeperIds: [],
    pickBudget: DEFAULT_PICK_BUDGET,
  });
});

test('a nonsense pick budget falls back to the default', () => {
  // A cleared number input yields NaN; letting it through would make every
  // picks-left calculation NaN and silently disable the floor rule.
  const storage = storageWith({
    'fht.draftSetup.v1': JSON.stringify({ keeperIds: [], pickBudget: 'lots' }),
  });
  assert.equal(loadSetup(storage).pickBudget, DEFAULT_PICK_BUDGET);
});

test('non-numeric keeper ids are dropped', () => {
  const storage = storageWith({
    'fht.draftSetup.v1': JSON.stringify({ keeperIds: [3, 'nope', 7], pickBudget: 14 }),
  });
  assert.deepEqual(loadSetup(storage).keeperIds, [3, 7]);
});

test('a hostile storage does not take the board down', () => {
  const hostile = {
    getItem: () => {
      throw new Error('private mode');
    },
    setItem: () => {
      throw new Error('quota exceeded');
    },
  } as unknown as Storage;

  assert.equal(loadSetup(hostile).pickBudget, DEFAULT_PICK_BUDGET);
  assert.doesNotThrow(() => saveSetup({ keeperIds: [1], pickBudget: 14 }, hostile));
});
