import { API_BASE, ApiError, qs, request } from './client';
import { getAccessToken, setAccessToken } from './token';
import type {
  AdminConversationsParams,
  AdminJobsParams,
  AdminMessageOut,
  AdminUsersParams,
  AnswerOut,
  AskIn,
  CacheClearOut,
  CacheStatsOut,
  ConversationOut,
  ConversationSummaryOut,
  DocumentOut,
  FeedbackIn,
  FeedbackOut,
  HealthOut,
  IndexRemovedOut,
  JobOut,
  LoginIn,
  Page,
  PageParams,
  SignupIn,
  StatsOut,
  TokenOut,
  UploadFields,
  UploadOut,
  UserOut,
  UserPatchIn,
} from './types';

// ---------------------------------------------------------------- auth

export const auth = {
  signup: (body: SignupIn) =>
    request<TokenOut>('/auth/signup', {
      method: 'POST',
      body,
      anonymous: true,
      credentials: 'include',
    }),
  login: (body: LoginIn) =>
    request<TokenOut>('/auth/login', {
      method: 'POST',
      body,
      anonymous: true,
      credentials: 'include',
    }),
  logout: () =>
    request<null>('/auth/logout', { method: 'POST', credentials: 'include' }).catch(() => null),
  me: () => request<UserOut>('/auth/me'),
};

// ---------------------------------------------------------------- ask

export const ask = {
  submit: (body: AskIn, signal?: AbortSignal) =>
    request<AnswerOut>('/ask', { method: 'POST', body, signal }),
  conversations: (p: PageParams = {}) =>
    request<Page<ConversationSummaryOut>>(
      `/conversations${qs({ offset: p.offset, limit: p.limit })}`,
    ),
  conversation: (id: string) =>
    request<ConversationOut>(`/conversations/${encodeURIComponent(id)}`),
  deleteConversation: (id: string) =>
    request<null>(`/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  feedback: (messageId: string, body: FeedbackIn) =>
    request<FeedbackOut>(`/messages/${encodeURIComponent(messageId)}/feedback`, {
      method: 'POST',
      body,
    }),
};

// ---------------------------------------------------------------- admin

export const admin = {
  stats: (days = 30) => request<StatsOut>(`/admin/stats${qs({ days })}`),
  conversations: (p: AdminConversationsParams) =>
    request<Page<AdminMessageOut>>(`/admin/conversations${qs({ ...p })}`),
  message: (id: string) => request<AdminMessageOut>(`/admin/messages/${encodeURIComponent(id)}`),
  documents: () => request<DocumentOut[]>('/admin/documents'),
  reindex: (id: string) =>
    request<UploadOut>(`/admin/documents/${encodeURIComponent(id)}/reindex`, { method: 'POST' }),
  /** Drops the active version's chunks, embeddings, figures and table rows; the file stays. */
  removeFromIndex: (id: string) =>
    request<IndexRemovedOut>(`/admin/documents/${encodeURIComponent(id)}/index`, {
      method: 'DELETE',
    }),
  jobs: (p: AdminJobsParams = {}) => request<Page<JobOut>>(`/admin/jobs${qs({ ...p })}`),
  users: (p: AdminUsersParams = {}) => request<Page<UserOut>>(`/admin/users${qs({ ...p })}`),
  patchUser: (id: string, body: UserPatchIn) =>
    request<UserOut>(`/admin/users/${encodeURIComponent(id)}`, { method: 'PATCH', body }),
  cacheStats: () => request<CacheStatsOut>('/admin/cache/stats'),
  clearCache: () => request<CacheClearOut>('/admin/cache', { method: 'DELETE' }),
};

/**
 * Multipart upload with progress. Uses XMLHttpRequest because fetch has no upload progress.
 * Mirrors the request() error handling (ApiError with code/message/request_id).
 */
export function uploadDocument(
  file: File,
  fields: UploadFields,
  onProgress?: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<UploadOut> {
  return new Promise<UploadOut>((resolve, reject) => {
    const fd = new FormData();
    fd.append('file', file, file.name);
    for (const [k, v] of Object.entries(fields)) fd.append(k, v);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE}/admin/documents`);
    xhr.setRequestHeader('Accept', 'application/json');
    const token = getAccessToken();
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
    };
    xhr.onerror = () => reject(new ApiError(0, null));
    xhr.onabort = () => reject(new DOMException('Aborted', 'AbortError'));
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        body = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as UploadOut);
      } else {
        const err =
          body && typeof body === 'object' && 'message' in body
            ? (body as { code: string; message: string; request_id?: string | null })
            : null;
        reject(new ApiError(xhr.status, err));
      }
    };
    signal?.addEventListener('abort', () => xhr.abort());
    xhr.send(fd);
  });
}

// ---------------------------------------------------------------- health

export const health = {
  ready: async (): Promise<HealthOut> => {
    // Not wrapped in request(): a 503 carries a HealthOut body we want to show, not an error.
    // The health routes sit at the server root (/health/*), outside the /api/v1 prefix.
    const res = await fetch('/health/ready', {
      headers: { Accept: 'application/json' },
    });
    const body = (await res.json().catch(() => null)) as HealthOut | null;
    if (body && typeof body.ready === 'boolean') return body;
    return { ready: false, checks: {} };
  },
};

export { setAccessToken };
