import type {
  AdvisorTextMessage,
  StoredAdvisorConversation,
  StoredAdvisorTurn,
} from '../types/keeperAdvisor';


export const STORAGE_PREFIX = 'fht.keeper-advisor.v1.';
const REQUEST_MESSAGE_LIMIT = 12;

type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem' | 'key' | 'length'>;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);


function isTurn(value: unknown): value is StoredAdvisorTurn {
  return isRecord(value) && typeof value.id === 'string' &&
    (value.role === 'user' || value.role === 'assistant') &&
    typeof value.content === 'string' && typeof value.created_at === 'string' &&
    (value.failed === undefined || typeof value.failed === 'boolean');
}


function isConversation(value: unknown): value is StoredAdvisorConversation {
  return isRecord(value) && value.schema_version === 1 &&
    typeof value.context_id === 'string' && typeof value.season === 'string' &&
    typeof value.updated_at === 'string' &&
    (value.conversation_summary === null ||
      typeof value.conversation_summary === 'string') &&
    Array.isArray(value.turns) && value.turns.every(isTurn);
}


export function emptyConversation(
  contextId: string, season: string,
): StoredAdvisorConversation {
  return {
    schema_version: 1,
    context_id: contextId,
    season,
    updated_at: '',
    conversation_summary: null,
    turns: [],
  };
}


export function loadConversation(
  storage: StorageLike, contextId: string, season: string,
): StoredAdvisorConversation {
  const raw = storage.getItem(`${STORAGE_PREFIX}${contextId}`);
  if (raw) {
    try {
      const parsed: unknown = JSON.parse(raw);
      if (isConversation(parsed) && parsed.context_id === contextId) return parsed;
    } catch {
      // fall through to a fresh conversation
    }
  }
  return emptyConversation(contextId, season);
}


export function saveConversation(
  storage: StorageLike, value: StoredAdvisorConversation,
): void {
  storage.setItem(`${STORAGE_PREFIX}${value.context_id}`, JSON.stringify(value));
}


export function listStaleConversations(
  storage: StorageLike, currentContextId: string,
): StoredAdvisorConversation[] {
  const conversations: StoredAdvisorConversation[] = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (!key || !key.startsWith(STORAGE_PREFIX)) continue;
    const raw = storage.getItem(key);
    if (!raw) continue;
    try {
      const parsed: unknown = JSON.parse(raw);
      if (isConversation(parsed) && parsed.context_id !== currentContextId) {
        conversations.push(parsed);
      }
    } catch {
      // ignore malformed records
    }
  }
  return conversations.sort((left, right) =>
    right.updated_at.localeCompare(left.updated_at));
}


export function appendTurn(
  value: StoredAdvisorConversation,
  turn: StoredAdvisorTurn,
  summary?: string | null,
): StoredAdvisorConversation {
  return {
    ...value,
    turns: [...value.turns, turn],
    conversation_summary: summary === undefined ? value.conversation_summary : summary,
    updated_at: turn.created_at,
  };
}


export function requestMessages(
  value: StoredAdvisorConversation,
): AdvisorTextMessage[] {
  return value.turns
    .filter((turn) => !turn.failed)
    .slice(-REQUEST_MESSAGE_LIMIT)
    .map((turn) => ({ role: turn.role, content: turn.content }));
}
