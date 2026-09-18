/**
 * The Konami code, as a hidden celebration on the draft board.
 *
 * Kept as a pure buffer-matcher rather than a listener so the sequence logic is
 * testable under the bare `node --test` runner -- the component only wires
 * keydown -> this -> a bit of state, per the src/lib rule.
 */

export const KONAMI_SEQUENCE = [
  'arrowup',
  'arrowup',
  'arrowdown',
  'arrowdown',
  'arrowleft',
  'arrowright',
  'arrowleft',
  'arrowright',
  'b',
  'a',
] as const;

/**
 * Fold one keypress into the rolling buffer. Lower-cased so `KeyboardEvent.key`
 * ('ArrowUp', 'B') matches, and capped at the sequence length so a long run of
 * keys still matches on its tail. Returns the new buffer and whether it now is
 * the code.
 */
export function konamiStep(
  buffer: readonly string[],
  key: string,
): { buffer: string[]; matched: boolean } {
  const next = [...buffer, key.toLowerCase()].slice(-KONAMI_SEQUENCE.length);
  const matched =
    next.length === KONAMI_SEQUENCE.length && next.every((k, i) => k === KONAMI_SEQUENCE[i]);
  return { buffer: next, matched };
}
