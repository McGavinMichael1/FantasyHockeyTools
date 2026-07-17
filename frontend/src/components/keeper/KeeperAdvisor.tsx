'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import type {
  KeeperAdvisorApiError,
  KeeperAdvisorApiSuccess,
  StoredAdvisorConversation,
  StoredAdvisorTurn,
} from '../../types/keeperAdvisor';
import { isAdvisorResponse } from '../../lib/keeperAdvisorSchema';
import {
  appendTurn,
  emptyConversation,
  listStaleConversations,
  loadConversation,
  requestMessages,
  saveConversation,
} from '../../lib/keeperAdvisorState';
import { KeeperAdvisorMessage } from './KeeperAdvisorMessage';
import styles from './KeeperAdvisor.module.css';


const SUGGESTED_PROMPTS = [
  "Why is the model's fourth keeper ahead of the next player?",
  'Would you keep Wyatt Johnston for multi-year upside?',
  'Does any current news change the recommendation?',
];

const RECOVERY_COMMAND = '.\\.venv\\Scripts\\python.exe main.py keeper';

interface Props {
  ready: boolean;
  contextId: string | null;
  season: string;
  generatedAt: string | null;
  playerNames: Record<number, string>;
}


function now(): string {
  return new Date().toISOString();
}


function makeId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `turn-${Math.random().toString(36).slice(2)}`;
}


function formatStaleLabel(conversation: StoredAdvisorConversation): string {
  const date = new Date(conversation.updated_at);
  const when = Number.isNaN(date.getTime())
    ? conversation.updated_at
    : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  return `${conversation.season || 'Previous season'} · ${when || 'earlier'}`;
}


export function KeeperAdvisor({
  ready,
  contextId,
  season,
  generatedAt,
  playerNames,
}: Props) {
  const [conversation, setConversation] = useState<StoredAdvisorConversation | null>(null);
  const [stale, setStale] = useState<StoredAdvisorConversation[]>([]);
  const [openedStale, setOpenedStale] = useState<StoredAdvisorConversation | null>(null);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmingReset, setConfirmingReset] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!ready || !contextId) {
      setConversation(null);
      setStale([]);
      return;
    }
    const storage = window.localStorage;
    setConversation(loadConversation(storage, contextId, season));
    setStale(listStaleConversations(storage, contextId));
    setOpenedStale(null);
    setNotice(null);
    return () => {
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, [ready, contextId, season]);

  const canSubmit = ready && !!contextId && !!conversation &&
    draft.trim().length > 0 && !sending;

  async function submit(text: string) {
    if (!contextId || !conversation) return;
    const trimmed = text.trim();
    if (!trimmed || sending) return;

    const storage = window.localStorage;
    const userTurn: StoredAdvisorTurn = {
      id: makeId(), role: 'user', content: trimmed, created_at: now(),
    };
    const withUser = appendTurn(conversation, userTurn);
    setConversation(withUser);
    saveConversation(storage, withUser);
    setDraft('');
    setNotice(null);
    setSending(true);

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const response = await fetch('/api/keeper-chat', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          context_id: contextId,
          messages: requestMessages(withUser),
          conversation_summary: withUser.conversation_summary,
        }),
        signal: controller.signal,
      });

      if (response.status === 409) {
        const body = (await response.json()) as KeeperAdvisorApiError;
        setNotice(
          'The keeper data was refreshed since this chat began. This conversation is now ' +
          'read-only — reload the page to start a current-context chat.',
        );
        markLastTurnFailed(storage, withUser);
        void body;
        return;
      }
      if (!response.ok) {
        markLastTurnFailed(storage, withUser);
        setNotice('The advisor could not answer that. You can retry the last message.');
        return;
      }

      const success = (await response.json()) as KeeperAdvisorApiSuccess;
      if (!isAdvisorResponse(success.reply)) {
        markLastTurnFailed(storage, withUser);
        setNotice('The advisor returned an unexpected answer. You can retry the last message.');
        return;
      }
      const assistantTurn: StoredAdvisorTurn = {
        id: makeId(), role: 'assistant', content: success.reply.answer,
        reply: success.reply, created_at: now(),
      };
      const complete = appendTurn(withUser, assistantTurn, success.conversation_summary);
      setConversation(complete);
      saveConversation(storage, complete);
    } catch (error) {
      if (controller.signal.aborted) return;
      markLastTurnFailed(storage, withUser);
      setNotice('The advisor request failed. You can retry the last message.');
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setSending(false);
    }
  }

  function markLastTurnFailed(
    storage: Storage, base: StoredAdvisorConversation,
  ) {
    const turns = base.turns.slice();
    const last = turns[turns.length - 1];
    if (last && last.role === 'user') {
      turns[turns.length - 1] = { ...last, failed: true };
    }
    const failed = { ...base, turns };
    setConversation(failed);
    saveConversation(storage, failed);
  }

  function retryLast() {
    if (!conversation) return;
    const last = conversation.turns[conversation.turns.length - 1];
    if (!last || last.role !== 'user') return;
    const storage = window.localStorage;
    const turns = conversation.turns.slice(0, -1);
    const reset = { ...conversation, turns };
    setConversation(reset);
    saveConversation(storage, reset);
    void submit(last.content);
  }

  function startNewConversation() {
    if (!contextId) return;
    const fresh = emptyConversation(contextId, season);
    setConversation(fresh);
    saveConversation(window.localStorage, fresh);
    setConfirmingReset(false);
    setNotice(null);
  }

  const lastTurn = conversation?.turns[conversation.turns.length - 1] ?? null;
  const canRetry = !sending && lastTurn?.role === 'user' && lastTurn.failed === true;

  const generatedLabel = useMemo(() => {
    if (!generatedAt) return null;
    const date = new Date(generatedAt);
    return Number.isNaN(date.getTime())
      ? null
      : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  }, [generatedAt]);

  if (!ready || !contextId) {
    return (
      <section className={styles.advisor} aria-label="Keeper advisor chat">
        <h3 className={styles.title}>Keeper advisor</h3>
        <p className={styles.unavailable}>
          The advisor needs a freshly generated keeper context. Run this, then refresh:
        </p>
        <code className={styles.code}>{RECOVERY_COMMAND}</code>
      </section>
    );
  }

  return (
    <section className={styles.advisor} aria-label="Keeper advisor chat">
      <div className={styles.header}>
        <h3 className={styles.title}>Keeper advisor</h3>
        {generatedLabel && <small>Context from {generatedLabel}</small>}
      </div>

      <div className={styles.thread} aria-live="polite">
        {conversation?.turns.length === 0 && (
          <p className={styles.empty}>
            Ask about your keepers. Every answer is grounded in the deterministic board and
            says clearly when it diverges from the model.
          </p>
        )}
        {conversation?.turns.map((turn) => (
          <div
            key={turn.id}
            className={turn.role === 'user' ? styles.userTurn : styles.assistantTurn}
          >
            {turn.role === 'user' ? (
              <p className={turn.failed ? styles.failedText : undefined}>{turn.content}</p>
            ) : turn.reply ? (
              <KeeperAdvisorMessage reply={turn.reply} playerNames={playerNames} />
            ) : (
              <p>{turn.content}</p>
            )}
          </div>
        ))}
        {sending && <p className={styles.pending} aria-live="polite">Thinking…</p>}
      </div>

      {notice && <p className={styles.notice} role="status">{notice}</p>}
      {canRetry && (
        <button type="button" className={styles.retry} onClick={retryLast}>
          Retry last message
        </button>
      )}

      <div className={styles.suggested}>
        {SUGGESTED_PROMPTS.map((prompt) => (
          <button
            key={prompt}
            type="button"
            className={styles.suggestion}
            onClick={() => setDraft(prompt)}
            disabled={sending}
          >
            {prompt}
          </button>
        ))}
      </div>

      <form
        className={styles.composer}
        onSubmit={(event) => {
          event.preventDefault();
          if (canSubmit) void submit(draft);
        }}
      >
        <label className={styles.srOnly} htmlFor="keeper-advisor-input">
          Ask the keeper advisor
        </label>
        <textarea
          id="keeper-advisor-input"
          className={styles.input}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Ask about a keeper decision…"
          rows={2}
          maxLength={4000}
        />
        <button type="submit" className={styles.send} disabled={!canSubmit}>
          Send
        </button>
      </form>

      <div className={styles.controls}>
        {confirmingReset ? (
          <span className={styles.confirm}>
            Clear this conversation?
            <button type="button" onClick={startNewConversation}>Yes, clear</button>
            <button type="button" onClick={() => setConfirmingReset(false)}>Cancel</button>
          </span>
        ) : (
          <button
            type="button"
            className={styles.reset}
            onClick={() => setConfirmingReset(true)}
            disabled={sending}
          >
            New conversation
          </button>
        )}
      </div>

      {stale.length > 0 && (
        <div className={styles.stale}>
          <h4>Previous data conversations</h4>
          <ul>
            {stale.map((entry) => (
              <li key={entry.context_id}>
                <button
                  type="button"
                  onClick={() =>
                    setOpenedStale(
                      openedStale?.context_id === entry.context_id ? null : entry,
                    )
                  }
                >
                  {formatStaleLabel(entry)}
                </button>
              </li>
            ))}
          </ul>
          {openedStale && (
            <div className={styles.staleThread} aria-label="Previous conversation (read-only)">
              <p className={styles.staleTag}>
                Read-only — this used older keeper data and cannot be continued.
              </p>
              {openedStale.turns.map((turn) => (
                <div
                  key={turn.id}
                  className={turn.role === 'user' ? styles.userTurn : styles.assistantTurn}
                >
                  {turn.role === 'assistant' && turn.reply ? (
                    <KeeperAdvisorMessage reply={turn.reply} playerNames={playerNames} />
                  ) : (
                    <p>{turn.content}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
