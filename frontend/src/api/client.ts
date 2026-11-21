import type { ErrorOut, TokenOut } from './types';
import { getAccessToken, setAccessToken } from './token';

export const API_BASE = '/api/v1';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;

  constructor(status: number, body: Partial<ErrorOut> | null, fallbackMessage?: string) {
    super(body?.message || fallbackMessage || defaultMessage(status));
    this.name = 'ApiError';
    this.status = status;
    this.code = body?.code || (status === 0 ? 'network' : `http_${status}`);
    this.requestId = body?.request_id ?? null;
  }

  get isServerError(): boolean {
    return this.status >= 500;
  }
}

function defaultMessage(status: number): string {
  if (status === 0) return 'Could not reach the server. Check your connection and try again.';
  if (status === 401) return 'Please sign in.';
  if (status === 403) return 'You do not have access to this.';
  if (status === 404) return 'Not found.';
  if (status === 429) return 'Too many requests. Please wait a moment.';
  if (status === 503) return 'The service is still preparing. Please try again in a moment.';
  if (status === 504) return 'The request took too long. Please try again.';
  return 'Something went wrong. Please try again.';
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

// ----------------------------------------------------------------- refresh

let refreshing: Promise<TokenOut | null> | null = null;
let onAuthLost: ((reason: 'expired' | 'logged_out') => void) | null = null;
let onTokenRefreshed: ((token: TokenOut) => void) | null = null;

/** The auth provider registers how the app reacts when a refresh fails or succeeds. */
export function registerAuthHooks(hooks: {
  onAuthLost: (reason: 'expired' | 'logged_out') => void;
  onTokenRefreshed: (token: TokenOut) => void;
}): void {
  onAuthLost = hooks.onAuthLost;
  onTokenRefreshed = hooks.onTokenRefreshed;
}

/**
 * POST /auth/refresh with the HttpOnly `pa_refresh` cookie. Concurrent callers share one request.
 * Returns null when the session cannot be restored.
 */
export function refreshSession(): Promise<TokenOut | null> {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
        headers: { Accept: 'application/json' },
      });
      if (!res.ok) return null;
      const token = (await res.json()) as TokenOut;
      setAccessToken(token.access_token);
      onTokenRefreshed?.(token);
      return token;
    } catch {
      return null;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

// ----------------------------------------------------------------- request

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  body?: unknown;
  /** multipart bodies are sent as-is; the browser sets the boundary */
  formData?: FormData;
  signal?: AbortSignal;
  /** skip the Authorization header and the 401 retry (auth endpoints) */
  anonymous?: boolean;
  /** send cookies (refresh/logout) */
  credentials?: RequestCredentials;
  headers?: Record<string, string>;
}

async function parseBody(res: Response): Promise<unknown> {
  if (res.status === 204) return null;
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function isErrorOut(v: unknown): v is ErrorOut {
  return !!v && typeof v === 'object' && typeof (v as ErrorOut).message === 'string';
}

async function doFetch(path: string, opts: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json', ...opts.headers };
  let body: BodyInit | undefined;
  if (opts.formData) {
    body = opts.formData;
  } else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.body);
  }
  if (!opts.anonymous) {
    const token = getAccessToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  return fetch(`${API_BASE}${path}`, {
    method: opts.method ?? 'GET',
    headers,
    body,
    signal: opts.signal,
    credentials: opts.credentials ?? 'same-origin',
  });
}

/**
 * Typed JSON request against /api/v1. On 401 `token_expired`/`unauthenticated` it refreshes once
 * and retries; if the refresh fails the auth provider is told and the error propagates.
 */
export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  let res: Response;
  try {
    res = await doFetch(path, opts);
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new ApiError(0, null);
  }

  if (res.status === 401 && !opts.anonymous) {
    const body = await parseBody(res);
    const code = isErrorOut(body) ? body.code : 'unauthenticated';
    if (code === 'token_expired' || code === 'unauthenticated') {
      const token = await refreshSession();
      if (token) {
        try {
          res = await doFetch(path, opts);
        } catch {
          throw new ApiError(0, null);
        }
      } else {
        setAccessToken(null);
        onAuthLost?.('expired');
        throw new ApiError(401, isErrorOut(body) ? body : null);
      }
    } else {
      throw new ApiError(401, isErrorOut(body) ? body : null);
    }
  }

  const body = await parseBody(res);
  if (!res.ok) {
    throw new ApiError(res.status, isErrorOut(body) ? body : null);
  }
  return body as T;
}

/** Build a query string, skipping undefined/empty values. */
export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}
