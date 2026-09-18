import assert from 'node:assert/strict';
import test from 'node:test';
import { KONAMI_SEQUENCE, konamiStep } from './konami';

/** Feed a list of keys through the matcher, returning the final result. */
function feed(keys: string[]): { buffer: string[]; matched: boolean } {
  let result = { buffer: [] as string[], matched: false };
  for (const k of keys) result = konamiStep(result.buffer, k);
  return result;
}

test('the full sequence matches', () => {
  assert.equal(feed([...KONAMI_SEQUENCE]).matched, true);
});

test('a wrong final key does not match', () => {
  const keys = [...KONAMI_SEQUENCE.slice(0, -1), 'x'];
  assert.equal(feed(keys).matched, false);
});

test('matching is case-insensitive on the letters (real events send "B"/"A")', () => {
  const keys = [
    'ArrowUp',
    'ArrowUp',
    'ArrowDown',
    'ArrowDown',
    'ArrowLeft',
    'ArrowRight',
    'ArrowLeft',
    'ArrowRight',
    'B',
    'A',
  ];
  assert.equal(feed(keys).matched, true);
});

test('junk keys before the code do not prevent a later match', () => {
  const keys = ['q', 'Enter', ' ', 'ArrowLeft', ...KONAMI_SEQUENCE];
  assert.equal(feed(keys).matched, true);
});

test('the buffer never grows past the sequence length', () => {
  const keys = Array.from({ length: 50 }, () => 'x');
  assert.equal(feed(keys).buffer.length, KONAMI_SEQUENCE.length);
});
