import { apiGet, apiSse } from '../../shared/api/client';
import type {
  ChainEvent,
  RegistryListResponse,
  RunRequest,
} from './types';

export function listAgents() {
  return apiGet<RegistryListResponse>('/agent-runner/agents');
}

export interface RunHandlers {
  onEvent: (evt: ChainEvent) => void;
  onError: (err: unknown) => void;
  onClose: () => void;
}

// Wraps apiSse to give callers typed ChainEvent payloads. Per
// [[raw-fetch-drifts-from-shared-client]]: NEVER bypass apiSse — it carries
// credentials=include + X-Data-Mode which the engine cookie/auth chain needs.
export async function runAgent(
  body: RunRequest,
  handlers: RunHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const sseHandlers: Parameters<typeof apiSse>[2] = {
    onEvent: (eventName, dataStr) => {
      try {
        const parsed = JSON.parse(dataStr) as ChainEvent;
        if (!parsed.event) (parsed as { event: string }).event = eventName;
        handlers.onEvent(parsed);
      } catch (err) {
        handlers.onError(err);
      }
    },
    onError: handlers.onError,
    onClose: handlers.onClose,
  };
  if (signal) sseHandlers.signal = signal;
  await apiSse('/agent-runner/run', body, sseHandlers);
}
