import type {
  AdvisorObjective,
  AdvisorTextMessage,
  KeeperAdvisorRequest,
  KeeperAdvisorResponse,
  ProviderAnswerDraft,
  TurnClassification,
} from '../types/keeperAdvisor';


const OBJECTIVES = new Set<AdvisorObjective>(['next_season', 'multi_year', 'balanced']);
const STANCES = new Set(['agrees', 'diverges', 'conditional']);
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((item) => typeof item === 'string');
const isNumberArray = (value: unknown): value is number[] =>
  Array.isArray(value) && value.every((item) => Number.isInteger(item));
const nullableNumber = (value: unknown) => value === null || typeof value === 'number';
const nullableString = (value: unknown) => value === null || typeof value === 'string';


export const TURN_CLASSIFICATION_SCHEMA = {
  type: 'object',
  properties: {
    objective: { type: 'string', enum: ['next_season', 'multi_year', 'balanced'] },
    needs_current_research: { type: 'boolean' },
    referenced_player_ids: { type: 'array', items: { type: 'integer' } },
    locked_player_ids: { type: 'array', items: { type: 'integer' } },
    excluded_player_ids: { type: 'array', items: { type: 'integer' } },
    conversation_summary: { type: 'string' },
  },
  required: [
    'objective', 'needs_current_research', 'referenced_player_ids',
    'locked_player_ids', 'excluded_player_ids', 'conversation_summary',
  ],
  additionalProperties: false,
} as const;


const TRADEOFF_SCHEMA = {
  type: 'object',
  properties: {
    out_player_id: { type: ['integer', 'null'] },
    in_player_id: { type: ['integer', 'null'] },
    projected_keeper_value_cost: { type: ['number', 'null'] },
  },
  required: ['out_player_id', 'in_player_id', 'projected_keeper_value_cost'],
  additionalProperties: false,
} as const;


const RESEARCH_SCHEMA = {
  type: 'object',
  properties: {
    used: { type: 'boolean' },
    current_information_verified: { type: ['boolean', 'null'] },
    as_of: { type: ['string', 'null'] },
    sources: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          url: { type: 'string' },
          published_at: { type: ['string', 'null'] },
          retrieved_at: { type: 'string' },
        },
        required: ['title', 'url', 'published_at', 'retrieved_at'],
        additionalProperties: false,
      },
    },
  },
  required: ['used', 'current_information_verified', 'as_of', 'sources'],
  additionalProperties: false,
} as const;


const RESPONSE_PROPERTIES = {
  stance: { type: 'string', enum: ['agrees', 'diverges', 'conditional'] },
  objective: { type: 'string', enum: ['next_season', 'multi_year', 'balanced'] },
  answer: { type: 'string' },
  model_view: { type: 'string' },
  recommendation: { type: 'string' },
  tradeoff: TRADEOFF_SCHEMA,
  qualitative_factors: { type: 'array', items: { type: 'string' } },
  uncertainty: { type: 'array', items: { type: 'string' } },
  research: RESEARCH_SCHEMA,
} as const;


export const PROVIDER_ANSWER_SCHEMA = {
  type: 'object',
  properties: {
    ...RESPONSE_PROPERTIES,
    recommended_player_ids: { type: 'array', items: { type: 'integer' } },
  },
  required: [...Object.keys(RESPONSE_PROPERTIES), 'recommended_player_ids'],
  additionalProperties: false,
} as const;


export function parseAdvisorRequest(value: unknown): KeeperAdvisorRequest | null {
  if (!isRecord(value) || typeof value.context_id !== 'string' ||
      value.context_id.length < 1 || value.context_id.length > 128 ||
      !Array.isArray(value.messages) || value.messages.length < 1 ||
      value.messages.length > 30 ||
      !(value.conversation_summary === null ||
        (typeof value.conversation_summary === 'string' &&
         value.conversation_summary.length <= 2000))) {
    return null;
  }
  const messages: AdvisorTextMessage[] = [];
  for (const message of value.messages) {
    if (!isRecord(message) ||
        (message.role !== 'user' && message.role !== 'assistant') ||
        typeof message.content !== 'string' || message.content.length < 1 ||
        message.content.length > 4000) {
      return null;
    }
    messages.push({ role: message.role, content: message.content });
  }
  return {
    context_id: value.context_id,
    messages,
    conversation_summary: value.conversation_summary,
  };
}


export function isTurnClassification(value: unknown): value is TurnClassification {
  return isRecord(value) && OBJECTIVES.has(value.objective as AdvisorObjective) &&
    typeof value.needs_current_research === 'boolean' &&
    isNumberArray(value.referenced_player_ids) &&
    isNumberArray(value.locked_player_ids) &&
    isNumberArray(value.excluded_player_ids) &&
    typeof value.conversation_summary === 'string';
}


function hasResponseShape(value: Record<string, unknown>): boolean {
  const tradeoff = value.tradeoff;
  const research = value.research;
  return STANCES.has(value.stance as string) &&
    OBJECTIVES.has(value.objective as AdvisorObjective) &&
    typeof value.answer === 'string' && typeof value.model_view === 'string' &&
    typeof value.recommendation === 'string' && isRecord(tradeoff) &&
    nullableNumber(tradeoff.out_player_id) &&
    nullableNumber(tradeoff.in_player_id) &&
    nullableNumber(tradeoff.projected_keeper_value_cost) &&
    isStringArray(value.qualitative_factors) && isStringArray(value.uncertainty) &&
    isRecord(research) && typeof research.used === 'boolean' &&
    (research.current_information_verified === null ||
     typeof research.current_information_verified === 'boolean') &&
    nullableString(research.as_of) && Array.isArray(research.sources) &&
    research.sources.every((source) => isRecord(source) &&
      typeof source.title === 'string' && typeof source.url === 'string' &&
      nullableString(source.published_at) && typeof source.retrieved_at === 'string');
}


export function isAdvisorResponse(value: unknown): value is KeeperAdvisorResponse {
  return isRecord(value) && hasResponseShape(value);
}


export function isProviderAnswerDraft(value: unknown): value is ProviderAnswerDraft {
  return isRecord(value) && hasResponseShape(value) &&
    isNumberArray(value.recommended_player_ids) &&
    value.recommended_player_ids.length === 4 &&
    new Set(value.recommended_player_ids).size === 4;
}
