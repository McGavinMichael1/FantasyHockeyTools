'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { draftKeyAction } from '@/lib/draftKeys';
import { tiers } from '@/lib/tiers';
import type { DraftPlayer, KeeperRecommendation, Position } from '@/types/player';
import type { RosterRules } from '@/lib/bestAvailable';
import { DEFAULT_ROSTER_RULES, shortlist } from '@/lib/bestAvailable';
import { DEFAULT_PICK_BUDGET, loadSetup, saveSetup } from '@/lib/draftSetup';
import { applyNudges, loadNudges, saveNudges, setNudge, type NudgeMap } from '@/lib/nudges';
import { konamiStep } from '@/lib/konami';
import OnTheClock from './OnTheClock';
import RosterPanel from './RosterPanel';
import DraftTable, { COLUMNS, type Column, type SortDir } from './DraftTable';
import { PositionChip } from './bits';
import type { Pick } from '@/lib/liveDraft';
import {
  addPick,
  draftedIds,
  loadPicks,
  myPicks,
  positionCounts,
  positionalRuns,
  REPLACEMENT_RANKS,
  removePick,
  savePicks,
  setMine,
  undoLast,
  withLiveVorp,
} from '@/lib/liveDraft';
import styles from './RinkTable.module.css';

/**
 * The Konami-code payoff: a rain of "WAHN 😭" over the board. Deterministic
 * scatter (index-derived, not Math.random) so a re-render does not reshuffle
 * it mid-fall. Click anywhere to dismiss; it also self-clears.
 */
function GoalCelebration({ onDone }: { onDone: () => void }) {
  return (
    <div className={styles.konami} onClick={onDone} role="presentation" aria-hidden="true">
      <div className={styles.konamiBanner}>WAHN 😭</div>
      {Array.from({ length: 28 }, (_, i) => (
        <span
          key={i}
          className={styles.konamiPuck}
          style={{
            left: `${(i * 37) % 100}%`,
            animationDelay: `${(i % 10) * 0.15}s`,
            animationDuration: `${2.5 + (i % 5) * 0.4}s`,
          }}
        >
          WAHN 😭
        </span>
      ))}
    </div>
  );
}

export default function DraftBoard({
  players,
  // Ranks the exported vorp was computed with (keeper-adjusted). Undefined for
  // snapshots exported before they existed -- the base ranks are what those used.
  replacementRanks = REPLACEMENT_RANKS,
  // Slot rules from api_export.py; older snapshots fall back to our own copy.
  // Typed as the two fields actually used, so a snapshot carrying only those
  // is honestly describable rather than cast into a fuller shape.
  rosterRules = DEFAULT_ROSTER_RULES,
  keeperOptions = [],
}: {
  players: DraftPlayer[];
  replacementRanks?: Record<Position, number>;
  rosterRules?: RosterRules;
  keeperOptions?: KeeperRecommendation[];
}) {
  const [sortKey, setSortKey] = useState('vorp');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  // An empty set means "all" -- the filter is additive, so C+L+R is expressible
  // and "forwards" is one click rather than three views.
  const [positions, setPositions] = useState<Set<Position>>(() => new Set());
  const [hideDrafted, setHideDrafted] = useState(false);
  const [query, setQuery] = useState('');
  // Up to three at once: on the clock the choice is between two or three
  // players, and one-at-a-time makes you hold the other in your head.
  const [expandedIds, setExpandedIds] = useState<Set<number>>(() => new Set());
  const [draftMode, setDraftMode] = useState(false);
  const [picks, setPicks] = useState<Pick[]>([]);
  const [keeperIds, setKeeperIds] = useState<Set<number>>(() => new Set());
  const [pickBudget, setPickBudget] = useState(DEFAULT_PICK_BUDGET);
  const [activeRow, setActiveRow] = useState(0);
  // Manual overrides for players the model never saw a role change on. See
  // lib/nudges; applied to the raw list so every ranking below re-derives.
  const [nudges, setNudges] = useState<NudgeMap>({});
  const [celebrate, setCelebrate] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  // Hydrate after mount, not during render: localStorage does not exist on the
  // server, and seeding state from it directly would mismatch the SSR output.
  useEffect(() => {
    const stored = loadPicks();
    if (stored.length > 0) {
      setPicks(stored);
      setDraftMode(true);
    }
    setNudges(loadNudges());
    const setup = loadSetup();
    setPickBudget(setup.pickBudget);
    // A saved setup wins; an unconfigured board starts from the keeper board's
    // recommendation, which is a suggestion the owner can clear.
    setKeeperIds(
      new Set(
        setup.keeperIds.length > 0
          ? setup.keeperIds
          : keeperOptions.map((k) => k.id).filter((id): id is number => id !== null),
      ),
    );
    // keeperOptions arrives with the payload and does not change afterwards.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Konami code -> a goal celebration. Passive: it never preventDefault's, so
  // the arrows still drive the draft loop while the code is being entered.
  useEffect(() => {
    let buffer: string[] = [];
    function onKey(event: KeyboardEvent) {
      const { buffer: next, matched } = konamiStep(buffer, event.key);
      buffer = next;
      if (matched) {
        buffer = [];
        setCelebrate(true);
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => {
    if (!celebrate) return;
    const timer = setTimeout(() => setCelebrate(false), 4500);
    return () => clearTimeout(timer);
  }, [celebrate]);

  // The list every ranking below reads. Nudging the projection here re-derives
  // VORP, tiers, best-available and the roster panel in one place -- none of
  // them know a manual override happened.
  const nudged = useMemo(() => applyNudges(players, nudges), [players, nudges]);

  const drafted = useMemo(() => draftedIds(picks), [picks]);
  const pickById = useMemo(() => new Map(picks.map((p) => [p.id, p])), [picks]);
  const playersById = useMemo(() => new Map(nudged.map((p) => [p.id, p])), [nudged]);

  const mine = useMemo(() => myPicks(picks), [picks]);
  const myCounts = useMemo(() => positionCounts(mine, nudged), [mine, nudged]);
  const keptCounts = useMemo(
    () =>
      positionCounts(
        [...keeperIds].map((id, i) => ({ id, pick: i + 1, mine: true })),
        nudged,
      ),
    [keeperIds, nudged],
  );

  function update(next: Pick[]) {
    savePicks(next);
    setPicks(next);
  }

  /** ✓ — taken by somebody. On a pick of yours it hands it to the room. */
  function markTaken(id: number) {
    const existing = pickById.get(id);
    if (!existing) update(addPick(picks, id, false));
    else if (existing.mine) update(setMine(picks, id, false));
    else update(removePick(picks, id));
  }

  /** ME — taken by you. On somebody else's pick it claims it. */
  function markMine(id: number) {
    const existing = pickById.get(id);
    if (!existing) update(addPick(picks, id, true));
    else if (!existing.mine) update(setMine(picks, id, true));
    else update(removePick(picks, id));
  }

  function resetDraft() {
    // Losing a live draft log to a stray click is the one unrecoverable
    // mistake this board can make.
    if (!window.confirm(`Clear all ${picks.length} picks? This cannot be undone.`)) return;
    update([]);
  }

  /**
   * Open a row's detail, keeping at most three open.
   *
   * Three is the most you can actually read side by side; past that the oldest
   * drops out rather than the click being refused, so a fourth compare does
   * something instead of appearing broken.
   */
  function toggleExpanded(id: number) {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else {
        if (next.size >= 3) next.delete(next.values().next().value as number);
        next.add(id);
      }
      return next;
    });
  }

  function toggleKeeper(id: number) {
    const next = new Set(keeperIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setKeeperIds(next);
    saveSetup({ keeperIds: [...next], pickBudget });
  }

  function changePickBudget(value: number) {
    const budget = Number.isFinite(value) && value >= 0 ? value : DEFAULT_PICK_BUDGET;
    setPickBudget(budget);
    saveSetup({ keeperIds: [...keeperIds], pickBudget: budget });
  }

  function changeNudge(id: number, factor: number) {
    const next = setNudge(nudges, id, factor);
    setNudges(next);
    saveNudges(next);
  }

  function resetNudges() {
    setNudges({});
    saveNudges({});
  }

  // VORP is recomputed against whoever is left, so the ranking re-sorts itself
  // as the pool thins. Outside draft mode the exported preseason value stands.
  const board = useMemo(
    () => (draftMode ? withLiveVorp(nudged, drafted, replacementRanks) : nudged),
    [nudged, drafted, draftMode, replacementRanks],
  );

  const runs = useMemo(
    () => (draftMode ? positionalRuns(nudged, drafted, replacementRanks) : []),
    [nudged, drafted, draftMode, replacementRanks],
  );

  // Useful before the draft too, so this is not gated on draft mode: with
  // nobody drafted it is the preseason tier board.
  const tierMap = useMemo(
    () => tiers(nudged, drafted, replacementRanks),
    [nudged, drafted, replacementRanks],
  );

  // Recommendations run against the LIVE board: their VORP has to mean the same
  // thing as the column the owner is reading, or the two quietly disagree.
  // Keepers are excluded from the pool -- they were never draftable.
  const candidates = useMemo(() => {
    if (!draftMode) return [];
    const gone = new Set([...drafted, ...keeperIds]);
    return shortlist(
      board,
      gone,
      myCounts,
      keptCounts,
      Math.max(0, pickBudget - mine.length),
      3,
      rosterRules,
    );
  }, [draftMode, board, drafted, keeperIds, myCounts, keptCounts, pickBudget, mine, rosterRules]);

  const rows = useMemo(() => {
    let data = board;
    if (positions.size > 0) data = data.filter((p) => positions.has(p.positionCode));
    if (draftMode && hideDrafted) data = data.filter((p) => !drafted.has(p.id));
    if (query) {
      const q = query.toLowerCase();
      data = data.filter((p) => p.full_name.toLowerCase().includes(q));
    }
    const col = COLUMNS.find((c) => c.key === sortKey);
    if (col?.sortValue) {
      const dir = sortDir === 'asc' ? 1 : -1;
      data = [...data].sort((a, b) => {
        // In draft mode the top row must be the best player still AVAILABLE --
        // that is the question being asked on the clock. Drafted players stay
        // listed (seeing who is gone is part of reading the room) but sink.
        if (draftMode) {
          const aGone = drafted.has(a.id) ? 1 : 0;
          const bGone = drafted.has(b.id) ? 1 : 0;
          if (aGone !== bGone) return aGone - bGone;
        }
        const av = col.sortValue!(a);
        const bv = col.sortValue!(b);
        if (typeof av === 'string' || typeof bv === 'string') {
          return String(av).localeCompare(String(bv)) * dir;
        }
        return (av - (bv as number)) * dir;
      });
    }
    return data;
  }, [board, positions, hideDrafted, query, sortKey, sortDir, draftMode, drafted]);

  // The draft-day keyboard loop: `/`, three letters, Enter. The decision half
  // lives in lib/draftKeys so it can be tested without a DOM; this only wires
  // actions to state.
  const applyAction = useCallback(
    (action: ReturnType<typeof draftKeyAction>) => {
      if (!action) return false;
      switch (action.type) {
        case 'focusSearch':
          searchRef.current?.focus();
          searchRef.current?.select();
          return true;
        case 'markTaken':
        case 'markMine': {
          const target = rows.find((p) => !drafted.has(p.id));
          if (!target) return false;
          update(addPick(picks, target.id, action.type === 'markMine'));
          setQuery('');
          return true;
        }
        case 'undo':
          if (picks.length === 0) return false;
          update(undoLast(picks));
          return true;
        case 'clearSearch':
          setQuery('');
          return true;
        case 'closeDetail':
          setExpandedIds(new Set());
          return true;
        case 'moveActive':
          setActiveRow((current) =>
            Math.max(0, Math.min(rows.length - 1, current + action.delta)),
          );
          return true;
      }
    },
    // `update` and `rows` close over the current picks/board every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, drafted, picks],
  );

  useEffect(() => {
    if (!draftMode) return;
    function onKeyDown(event: KeyboardEvent) {
      // A nudge (or pick-budget) field owns its own keys: undo and the arrows
      // fire from anywhere, and would hijack typing a number. The search box is
      // the one input the loop is built around, so it alone flows through.
      if (event.target instanceof HTMLInputElement && event.target !== searchRef.current) {
        return;
      }
      const inSearch = event.target === searchRef.current;
      const handled = applyAction(
        draftKeyAction({
          key: event.key,
          shiftKey: event.shiftKey,
          ctrlKey: event.ctrlKey,
          metaKey: event.metaKey,
          inSearch,
          hasQuery: query.length > 0,
          hasDetail: expandedIds.size > 0,
        }),
      );
      if (handled) event.preventDefault();
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [draftMode, applyAction, query, expandedIds]);

  // Keep the active row inside the list as filters change under it.
  useEffect(() => {
    setActiveRow((current) => Math.min(current, Math.max(0, rows.length - 1)));
  }, [rows.length]);

  function toggleSort(col: Column) {
    if (!col.sortValue) return;
    if (sortKey === col.key) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortKey(col.key);
      setSortDir(col.key === 'full_name' ? 'asc' : 'desc');
    }
  }

  const FORWARDS: Position[] = ['C', 'L', 'R'];
  const SINGLES: Position[] = ['C', 'L', 'R', 'D', 'G'];
  const forwardsOnly =
    positions.size === FORWARDS.length && FORWARDS.every((p) => positions.has(p));

  function togglePosition(target: Position) {
    const next = new Set(positions);
    if (next.has(target)) next.delete(target);
    else next.add(target);
    setPositions(next);
  }

  return (
    <section className={styles.section} aria-label="Draft board">
      {celebrate && <GoalCelebration onDone={() => setCelebrate(false)} />}
      <div className={styles.controls}>
        <input
          ref={searchRef}
          type="search"
          className={styles.search}
          placeholder={draftMode ? 'Search  ·  / focus, ⏎ taken, ⇧⏎ mine' : 'Search players'}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search players by name"
        />
        <div className={styles.positions} role="group" aria-label="Filter by position">
          <button
            className={`${styles.posButton} ${positions.size === 0 ? styles.posActive : ''}`}
            onClick={() => setPositions(new Set())}
            aria-pressed={positions.size === 0}
          >
            ALL
          </button>
          <button
            className={`${styles.posButton} ${forwardsOnly ? styles.posActive : ''}`}
            onClick={() => setPositions(forwardsOnly ? new Set() : new Set(FORWARDS))}
            aria-pressed={forwardsOnly}
            title="Centres and wingers"
          >
            F
          </button>
          {SINGLES.map((pos) => (
            <button
              key={pos}
              className={`${styles.posButton} ${positions.has(pos) ? styles.posActive : ''}`}
              onClick={() => togglePosition(pos)}
              aria-pressed={positions.has(pos)}
            >
              {pos}
            </button>
          ))}
        </div>
        <button
          className={`${styles.draftToggle} ${draftMode ? styles.draftToggleOn : ''}`}
          onClick={() => setDraftMode((on) => !on)}
          aria-pressed={draftMode}
          title="Mark players as drafted and recompute VORP against who is left"
        >
          Draft mode
        </button>
        {draftMode && (
          <button
            className={`${styles.draftToggle} ${hideDrafted ? styles.draftToggleOn : ''}`}
            onClick={() => setHideDrafted((on) => !on)}
            aria-pressed={hideDrafted}
            title="Hide players already off the board"
          >
            Hide taken
          </button>
        )}
        {draftMode && picks.length > 0 && (
          <>
            <button
              className={styles.resetButton}
              onClick={() => update(undoLast(picks))}
              title={`Undo pick ${picks.length}`}
            >
              ↩ Undo
            </button>
            <button className={styles.resetButton} onClick={resetDraft}>
              Clear {picks.length}
            </button>
          </>
        )}
        {Object.keys(nudges).length > 0 && (
          <button
            className={styles.resetButton}
            onClick={resetNudges}
            title="Remove every manual projection nudge"
          >
            Reset {Object.keys(nudges).length} nudge{Object.keys(nudges).length === 1 ? '' : 's'}
          </button>
        )}
        <span className={styles.count}>
          {rows.length} player{rows.length === 1 ? '' : 's'}
        </span>
      </div>

      {draftMode && (
        <RosterPanel
          players={nudged}
          counts={myCounts}
          keptCounts={keptCounts}
          keepers={keeperOptions}
          keeperIds={keeperIds}
          onToggleKeeper={toggleKeeper}
          picksMade={mine.length}
          pickBudget={pickBudget}
          onPickBudgetChange={changePickBudget}
          rules={rosterRules}
        />
      )}

      {draftMode && (
        <OnTheClock
          candidates={candidates}
          playersById={playersById}
          onPick={(id) => update(addPick(picks, id, true))}
        />
      )}

      {draftMode && (
        <div className={styles.runs} aria-label="Positional runs">
          {runs.map((run) => (
            <span
              key={run.position}
              className={styles.run}
              title={`${run.taken} of the top ${run.total} ${run.position} drafted`}
            >
              <PositionChip position={run.position} />
              <span className={styles.runTrack}>
                <span
                  className={`${styles.runBar} ${run.depleted >= 0.5 ? styles.runBarHot : ''}`}
                  style={{ width: `${Math.round(run.depleted * 100)}%` }}
                />
              </span>
              <span>
                {run.taken}/{run.total}
              </span>
            </span>
          ))}
        </div>
      )}

      <DraftTable
        rows={rows}
        draftMode={draftMode}
        pickById={pickById}
        tierMap={tierMap}
        expandedIds={expandedIds}
        activeRow={activeRow}
        sortKey={sortKey}
        sortDir={sortDir}
        onToggleExpanded={toggleExpanded}
        onSetActiveRow={setActiveRow}
        onToggleSort={toggleSort}
        onMarkTaken={markTaken}
        onMarkMine={markMine}
        nudges={nudges}
        onNudge={changeNudge}
      />
    </section>
  );
}
