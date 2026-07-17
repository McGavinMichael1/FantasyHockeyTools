import type {
  AdvisorResearch,
  AdvisorTextMessage,
  ProviderAnswerDraft,
  ResearchSource,
  TurnClassification,
} from '../types/keeperAdvisor';
import {
  isProviderAnswerDraft,
  isTurnClassification,
  PROVIDER_ANSWER_SCHEMA,
  TURN_CLASSIFICATION_SCHEMA,
} from './keeperAdvisorSchema';


const MESSAGES_URL = 'https://api.anthropic.com/v1/messages';
const ANTHROPIC_VERSION = '2023-06-01';
const REQUEST_TIMEOUT_MS = 120_000;

const WEB_SEARCH_TOOL = {
  type: 'web_search_20260209',
  name: 'web_search',
  max_uses: 3,
  allowed_callers: ['direct'],
  user_location: {
    type: 'approximate', country: 'CA', region: 'Ontario',
    timezone: 'America/Toronto',
  },
} as const;


export interface ProviderPrompt {
  system: string;
  messages: AdvisorTextMessage[];
}

export interface ProviderAnswerPrompt extends ProviderPrompt {
  allowWeb: boolean;
}

export interface ProviderAnswerResult {
  draft: ProviderAnswerDraft;
  research: AdvisorResearch;
}

export interface KeeperAdvisorProvider {
  classify(prompt: ProviderPrompt): Promise<TurnClassification>;
  answer(prompt: ProviderAnswerPrompt): Promise<ProviderAnswerResult>;
}

export class ProviderHttpError extends Error {
  constructor(public readonly status: number) {
    super(`Anthropic request failed with HTTP ${status}`);
  }
}


interface AnthropicResponse {
  content?: unknown;
  usage?: { server_tool_use?: { web_search_requests?: number } };
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);


function extractStructuredValue(response: AnthropicResponse): unknown {
  const blocks = Array.isArray(response.content) ? response.content : [];
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const block: unknown = blocks[index];
    if (isRecord(block) && block.type === 'text' && typeof block.text === 'string') {
      try {
        return JSON.parse(block.text);
      } catch {
        return undefined;
      }
    }
  }
  return undefined;
}


function observedResearch(response: AnthropicResponse, now: Date): AdvisorResearch {
  const nowIso = now.toISOString();
  const webSearchRequests =
    response.usage?.server_tool_use?.web_search_requests ?? 0;
  const blocks = Array.isArray(response.content) ? response.content : [];
  const sources: ResearchSource[] = [];
  const seenUrls = new Set<string>();
  for (const raw of blocks) {
    if (!isRecord(raw) || raw.type !== 'web_search_tool_result' ||
        !Array.isArray(raw.content)) {
      continue;
    }
    for (const item of raw.content) {
      if (!isRecord(item) || item.type !== 'web_search_result') continue;
      const url = typeof item.url === 'string' ? item.url : '';
      if (!/^https?:\/\//.test(url) || seenUrls.has(url)) continue;
      seenUrls.add(url);
      sources.push({
        title: typeof item.title === 'string' ? item.title : url,
        url,
        published_at: typeof item.page_age === 'string' ? item.page_age : null,
        retrieved_at: nowIso,
      });
    }
  }
  const used = webSearchRequests > 0 || sources.length > 0;
  return {
    used,
    current_information_verified: used ? sources.length > 0 : null,
    as_of: used ? nowIso : null,
    sources,
  };
}


export class AnthropicKeeperAdvisorProvider implements KeeperAdvisorProvider {
  constructor(private readonly config: {
    apiKey: string;
    model: string;
    fetchImpl?: typeof fetch;
    now?: () => Date;
  }) {
    if (!config.apiKey || !config.model) throw new Error('missing Anthropic configuration');
  }

  classify(prompt: ProviderPrompt): Promise<TurnClassification> {
    return this.request(prompt, TURN_CLASSIFICATION_SCHEMA, isTurnClassification, false)
      .then((result) => result.value);
  }

  answer(prompt: ProviderAnswerPrompt): Promise<ProviderAnswerResult> {
    return this.request(
      prompt, PROVIDER_ANSWER_SCHEMA, isProviderAnswerDraft, prompt.allowWeb,
    ).then(({ value, response }) => ({
      draft: value,
      research: observedResearch(response, this.config.now?.() ?? new Date()),
    }));
  }

  private async request<T>(
    prompt: ProviderPrompt,
    schema: object,
    guard: (value: unknown) => value is T,
    allowWeb: boolean,
  ): Promise<{ value: T; response: AnthropicResponse }> {
    const body: Record<string, unknown> = {
      model: this.config.model,
      max_tokens: 2500,
      system: prompt.system,
      messages: prompt.messages,
      output_config: {
        format: {
          type: 'json_schema',
          schema,
        },
      },
    };
    if (allowWeb) body.tools = [WEB_SEARCH_TOOL];
    const fetchImpl = this.config.fetchImpl ?? fetch;
    const response = await fetchImpl(MESSAGES_URL, {
      method: 'POST',
      headers: {
        'x-api-key': this.config.apiKey,
        'anthropic-version': ANTHROPIC_VERSION,
        'content-type': 'application/json',
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    if (!response.ok) throw new ProviderHttpError(response.status);
    const parsed = (await response.json()) as AnthropicResponse;
    const value = extractStructuredValue(parsed);
    if (!guard(value)) throw new Error('invalid Anthropic structured response');
    return { value, response: parsed };
  }
}
