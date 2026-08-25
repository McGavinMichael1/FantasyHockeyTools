/**
 * The draft-day keyboard loop.
 *
 * A pick has to be recorded in the time it takes someone to say a name out
 * loud. The mouse round trip -- click the field, type, reach for the row,
 * click the checkmark, clear the field -- is the slowest part of using this
 * board, and it happens ~180 times in an evening.
 *
 * The loop this enables is: `/`, three letters, Enter. Roughly two seconds.
 *
 * Kept as a pure key -> action function rather than handlers inside the
 * component so it can be tested at all: the frontend test runner is bare
 * `node --test` with no DOM.
 */

export interface KeyContext {
  key: string;
  shiftKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
  /** Focus is inside the search input. */
  inSearch: boolean;
  /** The search box has something in it. */
  hasQuery: boolean;
  /** A row's detail panel is open. */
  hasDetail: boolean;
}

export type DraftAction =
  | { type: 'focusSearch' }
  | { type: 'markTaken' }
  | { type: 'markMine' }
  | { type: 'undo' }
  | { type: 'clearSearch' }
  | { type: 'closeDetail' }
  | { type: 'moveActive'; delta: number };

export function draftKeyAction(ctx: KeyContext): DraftAction | null {
  // Undo first, and from anywhere: the hands live in the search box for the
  // whole draft, so an undo needing a click first would never be reachable
  // when it is actually wanted.
  if ((ctx.ctrlKey || ctx.metaKey) && ctx.key.toLowerCase() === 'z') {
    return { type: 'undo' };
  }

  if (ctx.key === '/') {
    // Inside the field a slash is just a character -- otherwise the one thing
    // you cannot search for is what got you into the field.
    return ctx.inSearch ? null : { type: 'focusSearch' };
  }

  if (ctx.key === 'Enter') {
    // With no query the top row is the board leader, so a stray Enter would
    // hand away the best player on the board. Require a search first.
    if (!ctx.inSearch || !ctx.hasQuery) return null;
    return ctx.shiftKey ? { type: 'markMine' } : { type: 'markTaken' };
  }

  if (ctx.key === 'Escape') {
    if (ctx.hasQuery) return { type: 'clearSearch' };
    if (ctx.hasDetail) return { type: 'closeDetail' };
    return null;
  }

  if (ctx.key === 'ArrowDown') return { type: 'moveActive', delta: 1 };
  if (ctx.key === 'ArrowUp') return { type: 'moveActive', delta: -1 };

  return null;
}
