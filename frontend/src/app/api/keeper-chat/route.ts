import type { AdvisorContext, KeeperAdvisorApiError } from '../../../types/keeperAdvisor';
import type { KeeperAdvisorProvider } from '../../../lib/anthropicKeeperAdvisor';
import {
  AnthropicKeeperAdvisorProvider,
  ProviderHttpError,
} from '../../../lib/anthropicKeeperAdvisor';
import { loadAdvisorContext } from '../../../lib/keeperAdvisorContext';
import { parseAdvisorRequest } from '../../../lib/keeperAdvisorSchema';
import {
  answerKeeperQuestion,
  InvalidProviderResponseError,
} from '../../../lib/keeperAdvisorService';


export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

type ErrorCode = KeeperAdvisorApiError['error']['code'];

export interface KeeperChatDependencies {
  loadContext?: () => AdvisorContext;
  providerFactory?: (apiKey: string, model: string) => KeeperAdvisorProvider;
  environment?: { ANTHROPIC_API_KEY?: string; KEEPER_ADVISOR_MODEL?: string };
}


function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'content-type': 'application/json',
      'cache-control': 'no-store',
    },
  });
}


function errorResponse(
  status: number,
  code: ErrorCode,
  message: string,
  currentContextId?: string,
): Response {
  const body: KeeperAdvisorApiError = { error: { code, message } };
  if (currentContextId !== undefined) body.error.current_context_id = currentContextId;
  return json(status, body);
}


function logError(code: string, error: unknown): void {
  const name = error instanceof Error ? error.constructor.name : typeof error;
  const status = error instanceof ProviderHttpError ? ` status=${error.status}` : '';
  console.error(`keeper-chat ${code}: ${name}${status}`);
}


export function createKeeperChatPost(dependencies: KeeperChatDependencies = {}) {
  return async (request: Request): Promise<Response> => {
    let payload: unknown;
    try {
      payload = await request.json();
    } catch {
      return errorResponse(400, 'invalid_request', 'Request body must be JSON.');
    }
    const parsed = parseAdvisorRequest(payload);
    if (!parsed || parsed.messages[parsed.messages.length - 1].role !== 'user') {
      return errorResponse(
        400, 'invalid_request',
        'Request must contain bounded chat messages ending with a user message.',
      );
    }

    let context: AdvisorContext;
    try {
      context = (dependencies.loadContext ?? loadAdvisorContext)();
    } catch (error) {
      logError('missing_context', error);
      return errorResponse(
        503, 'missing_context',
        'The keeper advisor context is unavailable. Run main.py keeper to generate it.',
      );
    }
    if (parsed.context_id !== context.context_id) {
      return errorResponse(
        409, 'stale_context',
        'The keeper advisor context has been regenerated since this conversation started.',
        context.context_id,
      );
    }

    const environment = dependencies.environment ?? process.env;
    const apiKey = environment.ANTHROPIC_API_KEY;
    const model = environment.KEEPER_ADVISOR_MODEL;
    if (!apiKey || !model) {
      return errorResponse(
        503, 'missing_configuration',
        'ANTHROPIC_API_KEY and KEEPER_ADVISOR_MODEL must be configured on the server.',
      );
    }
    const provider = dependencies.providerFactory
      ? dependencies.providerFactory(apiKey, model)
      : new AnthropicKeeperAdvisorProvider({ apiKey, model });

    try {
      const success = await answerKeeperQuestion({ context, request: parsed, provider });
      return json(200, success);
    } catch (error) {
      if (error instanceof InvalidProviderResponseError) {
        logError('invalid_provider_response', error);
        return errorResponse(
          502, 'invalid_provider_response',
          'The advisor returned an invalid structured answer.',
        );
      }
      logError('provider_error', error);
      return errorResponse(502, 'provider_error', 'The advisor request failed.');
    }
  };
}


export const POST = createKeeperChatPost();
