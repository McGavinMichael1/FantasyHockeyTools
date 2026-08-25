import assert from 'node:assert/strict';
import test from 'node:test';
import { draftKeyAction, type KeyContext } from './draftKeys';

function ctx(overrides: Partial<KeyContext> = {}): KeyContext {
  return {
    key: 'x',
    shiftKey: false,
    ctrlKey: false,
    metaKey: false,
    inSearch: false,
    hasQuery: false,
    hasDetail: false,
    ...overrides,
  };
}

test('slash focuses the search field', () => {
  assert.deepEqual(draftKeyAction(ctx({ key: '/' })), { type: 'focusSearch' });
});

test('slash inside the search field types a slash instead', () => {
  // Otherwise the one character you cannot search for is the one that got you
  // into the field.
  assert.equal(draftKeyAction(ctx({ key: '/', inSearch: true })), null);
});

test('Enter in the search marks the top match taken', () => {
  assert.deepEqual(
    draftKeyAction(ctx({ key: 'Enter', inSearch: true, hasQuery: true })),
    { type: 'markTaken' },
  );
});

test('Shift+Enter in the search marks the top match as mine', () => {
  assert.deepEqual(
    draftKeyAction(ctx({ key: 'Enter', inSearch: true, hasQuery: true, shiftKey: true })),
    { type: 'markMine' },
  );
});

test('Enter on an empty query does nothing', () => {
  // With no query the top row is the board leader. Drafting McDavid to another
  // team because a stray Enter landed is exactly the mistake this guard exists
  // to prevent.
  assert.equal(draftKeyAction(ctx({ key: 'Enter', inSearch: true, hasQuery: false })), null);
});

test('Enter outside the search does nothing', () => {
  assert.equal(draftKeyAction(ctx({ key: 'Enter', hasQuery: true })), null);
});

test('Ctrl+Z undoes the last pick', () => {
  assert.deepEqual(draftKeyAction(ctx({ key: 'z', ctrlKey: true })), { type: 'undo' });
});

test('Cmd+Z undoes the last pick', () => {
  assert.deepEqual(draftKeyAction(ctx({ key: 'z', metaKey: true })), { type: 'undo' });
});

test('undo works from inside the search field', () => {
  // The hands are in the search box for the whole draft; an undo that needed a
  // click first would not be reachable when it is actually wanted.
  assert.deepEqual(
    draftKeyAction(ctx({ key: 'z', ctrlKey: true, inSearch: true })),
    { type: 'undo' },
  );
});

test('a bare z is not an undo', () => {
  assert.equal(draftKeyAction(ctx({ key: 'z' })), null);
});

test('Escape clears the query before closing the detail', () => {
  assert.deepEqual(
    draftKeyAction(ctx({ key: 'Escape', hasQuery: true, hasDetail: true })),
    { type: 'clearSearch' },
  );
});

test('Escape closes the detail when there is no query', () => {
  assert.deepEqual(
    draftKeyAction(ctx({ key: 'Escape', hasDetail: true })),
    { type: 'closeDetail' },
  );
});

test('Escape with nothing to dismiss does nothing', () => {
  assert.equal(draftKeyAction(ctx({ key: 'Escape' })), null);
});

test('arrow keys move the active row', () => {
  assert.deepEqual(draftKeyAction(ctx({ key: 'ArrowDown' })), { type: 'moveActive', delta: 1 });
  assert.deepEqual(draftKeyAction(ctx({ key: 'ArrowUp' })), { type: 'moveActive', delta: -1 });
});

test('an unmapped key does nothing', () => {
  assert.equal(draftKeyAction(ctx({ key: 'q' })), null);
});
