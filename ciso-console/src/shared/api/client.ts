// Typed fetch wrapper for the engine API.
// All CISO Console API calls go through this. Targets /api/v1/* — the alias
// middleware on the engine rewrites to the internal /api/* routes.
//
// Discriminated-union result type per global CLAUDE.md error-handling rule:
// callers branch on result.ok, never throw across boundaries.

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '/api/v1').replace(/\/+$/, '');

// S52: Reads localStorage directly (not the signal) so this module has no
// dependency on the toggle component. Tolerates absent localStorage (e.g.
// SSR or private mode) and defaults to 'v1'.
function readDataMode(): 'v1' | 'v2' {
  try {
    return window.localStorage.getItem('aigovern_data_mode') === 'v2' ? 'v2' : 'v1';
  } catch {
    return 'v1';
  }
}

export type ApiOk<T> = { ok: true; status: number; data: T };
export type ApiErr = { ok: false; status: number; detail: string; trace_id?: string };
export type ApiResult<T> = ApiOk<T> | ApiErr;

export interface ApiRequest {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined>;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: ApiRequest['query']): string {
  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  const url = `${BASE_URL}${cleanPath}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null) params.append(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

export async function apiRequest<T>(path: string, req: ApiRequest = {}): Promise<ApiResult<T>> {
  const { method = 'GET', body, query, signal } = req;
  const url = buildUrl(path, query);
  const init: RequestInit = {
    method,
    credentials: 'include',
    headers: { Accept: 'application/json', 'X-Data-Mode': readDataMode() },
  };
  if (signal) init.signal = signal;
  if (body !== undefined) {
    init.headers = { ...init.headers, 'Content-Type': 'application/json' };
    init.body = JSON.stringify(body);
  }

  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (err) {
    return { ok: false, status: 0, detail: err instanceof Error ? err.message : 'Network error' };
  }

  const ct = response.headers.get('content-type') ?? '';
  let payload: unknown = null;
  if (ct.includes('application/json')) {
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const detail = extractDetail(payload) ?? `HTTP ${response.status}`;
    const trace_id = extractTraceId(payload);
    return trace_id
      ? { ok: false, status: response.status, detail, trace_id }
      : { ok: false, status: response.status, detail };
  }

  return { ok: true, status: response.status, data: payload as T };
}

function extractDetail(payload: unknown): string | undefined {
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const d = (payload as { detail: unknown }).detail;
    if (typeof d === 'string') return d;
    if (d && typeof d === 'object') return JSON.stringify(d);
  }
  return undefined;
}

function extractTraceId(payload: unknown): string | undefined {
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const d = (payload as { detail: unknown }).detail;
    if (d && typeof d === 'object' && 'trace_id' in d) {
      const t = (d as { trace_id: unknown }).trace_id;
      if (typeof t === 'string') return t;
    }
  }
  return undefined;
}

export const apiGet = <T>(path: string, query?: ApiRequest['query']) =>
  apiRequest<T>(path, query ? { method: 'GET', query } : { method: 'GET' });

export const apiPost = <T>(path: string, body?: unknown) =>
  apiRequest<T>(path, { method: 'POST', body });

export const apiDelete = <T>(path: string) =>
  apiRequest<T>(path, { method: 'DELETE' });

// ---------------------------------------------------------------------------
// SSE (Server-Sent Events) — S72 (port of team-portal S69 wrapper)
// ---------------------------------------------------------------------------
// Native EventSource doesn't support POST bodies, so we use
// @microsoft/fetch-event-source which gives full fetch() semantics
// (POST + body + credentials + custom headers) on the SSE wire format.
//
// Per [[raw-fetch-drifts-from-shared-client]]: this wrapper is the ONLY
// way SPA code should consume SSE. Bypassing it would drop credentials or
// X-Data-Mode and produce the F-019-class cross-origin auth bug.

import { fetchEventSource } from '@microsoft/fetch-event-source';

export interface SseHandlers {
  onEvent: (event: string, data: string) => void;
  onError?: (err: unknown) => void;
  onClose?: () => void;
  signal?: AbortSignal;
}

export async function apiSse(
  path: string,
  body: unknown,
  handlers: SseHandlers,
): Promise<void> {
  const url = buildUrl(path);
  await fetchEventSource(url, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      'X-Data-Mode': readDataMode(),
    },
    body: JSON.stringify(body),
    signal: handlers.signal ?? null,
    // openWhenHidden: keep the stream alive when the tab is backgrounded.
    openWhenHidden: true,
    onmessage(msg) {
      handlers.onEvent(msg.event || 'message', msg.data);
    },
    onerror(err) {
      handlers.onError?.(err);
      // Throw to stop fetchEventSource auto-retry — we want fail-fast UI.
      throw err;
    },
    onclose() {
      handlers.onClose?.();
    },
  });
}
