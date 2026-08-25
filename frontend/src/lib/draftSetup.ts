/**
 * Draft-day setup: the two things the board cannot derive.
 *
 * Which players YOU are keeping decides both your starting-slot floors and your
 * positional caps, and how many picks you hold decides when the floors start
 * reserving picks. Neither is in the export: the keeper list on disk is last
 * season's, and draft length depends on the final league-wide keeper count.
 * Guessing either would be worse than asking once.
 *
 * Kept separate from the pick log because it is set before the draft and barely
 * changes during it, while the log changes every ninety seconds.
 */

const STORAGE_KEY = 'fht.draftSetup.v1';

/** 18 rounds less the 4 keepers the league rule costs. */
export const DEFAULT_PICK_BUDGET = 14;

export interface DraftSetup {
  /** playerIds you are keeping, so their slots count as filled. */
  keeperIds: number[];
  /** How many picks you actually hold this draft. */
  pickBudget: number;
}

const DEFAULT_SETUP: DraftSetup = { keeperIds: [], pickBudget: DEFAULT_PICK_BUDGET };

function parseSetup(raw: unknown): DraftSetup {
  if (typeof raw !== 'object' || raw === null) return { ...DEFAULT_SETUP };
  const { keeperIds, pickBudget } = raw as Partial<DraftSetup>;

  return {
    keeperIds: Array.isArray(keeperIds)
      ? keeperIds.filter((id): id is number => typeof id === 'number')
      : [],
    // A cleared number input yields NaN; letting it through would make every
    // picks-left calculation NaN and silently disable the floor rule.
    pickBudget:
      typeof pickBudget === 'number' && Number.isFinite(pickBudget) && pickBudget >= 0
        ? pickBudget
        : DEFAULT_PICK_BUDGET,
  };
}

export function loadSetup(storage?: Storage): DraftSetup {
  try {
    const store = storage ?? globalThis.localStorage;
    const raw = store?.getItem(STORAGE_KEY);
    if (raw == null) return { ...DEFAULT_SETUP };
    return parseSetup(JSON.parse(raw) as unknown);
  } catch {
    return { ...DEFAULT_SETUP };
  }
}

export function saveSetup(setup: DraftSetup, storage?: Storage): void {
  try {
    const store = storage ?? globalThis.localStorage;
    store?.setItem(STORAGE_KEY, JSON.stringify(setup));
  } catch {
    // Persistence is a convenience; never let it break the board.
  }
}
