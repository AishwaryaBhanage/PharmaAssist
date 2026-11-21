import { delay, http, HttpResponse } from 'msw';
import type {
  AdminMessageOut,
  AnswerOut,
  AskIn,
  ConversationOut,
  ErrorOut,
  FeedbackIn,
  FeedbackOut,
  IndexRemovedOut,
  JobOut,
  LoginIn,
  MessageOut,
  Page,
  SignupIn,
  TokenOut,
  UploadOut,
  UserOut,
  UserPatchIn,
  VersionOut,
} from '@/api/types';
import { JOB_STAGES } from '@/lib/constants';
import * as F from './fixtures';

const BASE = '/api/v1';
const url = (p: string) => `${BASE}${p}`;

/** Mutable mock state; `resetMocks()` restores the fixtures between tests. */
export const state = {
  users: [] as F.MockUser[],
  conversations: [] as ConversationOut[],
  adminMessages: [] as AdminMessageOut[],
  documents: [] as typeof F.documents,
  jobs: [] as JobOut[],
  /** access token -> user id */
  tokens: new Map<string, string>(),
  /** the "cookie": user id with a live refresh session */
  refreshUser: null as string | null,
  /** when true, the next authenticated request answers 401 token_expired once (tests) */
  expireNextRequest: false,
  ready: true,
  cache: { ...F.cacheStats },
  /** index generation; bumped when a document is removed from the index */
  generation: F.health.generation ?? 0,
  nextId: 100,
  /** per-conversation owner */
  owners: new Map<string, string>(),
  /** network delay in ms (0 in tests) */
  latency: 0,
};

const SESSION_KEY = 'pa_mock_session';

export function resetMocks(opts: { latency?: number } = {}): void {
  state.users = F.users.map((u) => ({ ...u }));
  state.conversations = F.conversations.map((c) => ({
    ...c,
    messages: c.messages.map((m) => ({ ...m })),
  }));
  state.adminMessages = F.adminMessages.map((m) => ({ ...m }));
  state.documents = F.documents.map((d) => ({ ...d }));
  state.jobs = F.jobs.map((j) => ({ ...j }));
  state.tokens = new Map();
  state.refreshUser = null;
  state.expireNextRequest = false;
  state.ready = true;
  state.cache = { ...F.cacheStats };
  state.generation = F.health.generation ?? 0;
  state.nextId = 100;
  state.owners = new Map([
    ['c_1', 'u_dana'],
    ['c_2', 'u_dana'],
  ]);
  state.latency = opts.latency ?? 0;
  try {
    const saved = sessionStorage.getItem(SESSION_KEY);
    if (saved && state.users.some((u) => u.id === saved)) state.refreshUser = saved;
  } catch {
    /* no storage */
  }
}

resetMocks();

// ---------------------------------------------------------------- helpers

function err(
  status: number,
  code: ErrorOut['code'],
  message: string,
  requestId = `req_${Math.random().toString(36).slice(2, 10)}`,
) {
  return HttpResponse.json<ErrorOut>({ code, message, request_id: requestId }, { status });
}

function nextId(prefix: string): string {
  return `${prefix}_${state.nextId++}`;
}

function issueToken(user: F.MockUser): TokenOut {
  const token = `tok_${user.id}_${state.nextId++}`;
  state.tokens.set(token, user.id);
  state.refreshUser = user.id;
  try {
    sessionStorage.setItem(SESSION_KEY, user.id);
  } catch {
    /* no storage */
  }
  return { access_token: token, token_type: 'bearer', expires_in: 900, user: F.publicUser(user) };
}

function tokenResponse(t: TokenOut) {
  return HttpResponse.json(t, {
    headers: {
      'Set-Cookie': `pa_refresh=${state.refreshUser}; Path=/api/v1/auth; HttpOnly; SameSite=Lax`,
    },
  });
}

type Auth = { user: F.MockUser } | { error: ReturnType<typeof err> };

function authenticate(request: Request): Auth {
  const header = request.headers.get('authorization') ?? '';
  const token = header.replace(/^Bearer\s+/i, '');
  if (!token) return { error: err(401, 'unauthenticated', 'Sign in to continue.') };
  if (state.expireNextRequest) {
    state.expireNextRequest = false;
    return { error: err(401, 'token_expired', 'Your session token expired.') };
  }
  const userId = state.tokens.get(token);
  const user = userId ? state.users.find((u) => u.id === userId) : undefined;
  if (!user) return { error: err(401, 'token_expired', 'Your session token expired.') };
  if (!user.is_active) return { error: err(403, 'forbidden', 'This account is deactivated.') };
  return { user };
}

function requireAdmin(a: Auth): Auth {
  if ('error' in a) return a;
  if (a.user.role !== 'admin') return { error: err(403, 'forbidden', 'Admin role required.') };
  return a;
}

function page<T>(items: T[], sp: URLSearchParams): Page<T> {
  const offset = Math.max(0, Number(sp.get('offset') ?? 0) || 0);
  const limit = Math.min(200, Math.max(1, Number(sp.get('limit') ?? 25) || 25));
  return { items: items.slice(offset, offset + limit), total: items.length, offset, limit };
}

async function wait() {
  if (state.latency) await delay(state.latency);
}

/** Each poll advances a running job one stage, so the UI's live polling has something to show. */
function advanceJobs(): void {
  for (const job of state.jobs) {
    if (job.status !== 'running' && job.status !== 'queued') continue;
    const stage = job.stage ?? 'queued';
    const i = JOB_STAGES.indexOf(stage as (typeof JOB_STAGES)[number]);
    const next = JOB_STAGES[i + 1];
    if (!job.started_at) job.started_at = new Date().toISOString();
    if (!next) continue;
    job.stage = next;
    if (next === 'active') {
      job.status = 'active';
      job.finished_at = new Date().toISOString();
      const doc = state.documents.find((d) => d.id === job.document_id);
      if (doc) {
        const v: VersionOut = {
          id: job.version_id,
          document_id: doc.id,
          file_name: doc.latest_version?.file_name ?? `${doc.id}.pdf`,
          content_type: doc.latest_version?.content_type ?? 'application/pdf',
          bytes: doc.latest_version?.bytes ?? 1_000_000,
          pages: doc.latest_version?.pages ?? 100,
          status: 'active',
          error: null,
          chunk_count: 500 + Math.floor(Math.random() * 100),
          figure_count: doc.active_version?.figure_count ?? 0,
          created_at: job.queued_at,
          activated_at: job.finished_at,
        };
        doc.active_version = v;
        doc.latest_version = v;
      }
    }
  }
}

// ---------------------------------------------------------------- handlers

export const handlers = [
  // ---- health
  http.get('/health/ready', async () => {
    await wait();
    if (!state.ready) {
      return HttpResponse.json(
        { ...F.health, ready: false, checks: { ...F.health.checks, cache: false } },
        { status: 503 },
      );
    }
    return HttpResponse.json(F.health);
  }),

  // ---- auth
  http.post(url('/auth/signup'), async ({ request }) => {
    await wait();
    const body = (await request.json()) as SignupIn;
    if (!body.email || !body.password)
      return err(422, 'validation_error', 'Email and password are required.');
    if (body.password.length < 10)
      return err(422, 'weak_password', 'Password must be at least 10 characters.');
    if (state.users.some((u) => u.email.toLowerCase() === body.email.toLowerCase())) {
      return err(409, 'email_taken', 'An account with this email already exists.');
    }
    const user: F.MockUser = {
      id: nextId('u'),
      email: body.email,
      display_name: body.display_name ?? '',
      role: 'staff',
      is_active: true,
      created_at: new Date().toISOString(),
      last_login_at: new Date().toISOString(),
      password: body.password,
    };
    state.users.push(user);
    return tokenResponse(issueToken(user));
  }),

  http.post(url('/auth/login'), async ({ request }) => {
    await wait();
    const body = (await request.json()) as LoginIn;
    const user = state.users.find((u) => u.email.toLowerCase() === body.email.toLowerCase());
    if (!user || user.password !== body.password)
      return err(401, 'invalid_credentials', 'Email or password is incorrect.');
    if (!user.is_active) return err(403, 'forbidden', 'This account is deactivated.');
    user.last_login_at = new Date().toISOString();
    return tokenResponse(issueToken(user));
  }),

  http.post(url('/auth/refresh'), async () => {
    await wait();
    const user = state.refreshUser
      ? state.users.find((u) => u.id === state.refreshUser)
      : undefined;
    if (!user || !user.is_active) return err(401, 'unauthenticated', 'No active session.');
    return tokenResponse(issueToken(user));
  }),

  http.post(url('/auth/logout'), async () => {
    await wait();
    state.refreshUser = null;
    state.tokens.clear();
    try {
      sessionStorage.removeItem(SESSION_KEY);
    } catch {
      /* no storage */
    }
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(url('/auth/me'), async ({ request }) => {
    await wait();
    const a = authenticate(request);
    if ('error' in a) return a.error;
    return HttpResponse.json(F.publicUser(a.user));
  }),

  // ---- ask
  http.post(url('/ask'), async ({ request }) => {
    const a = authenticate(request);
    if ('error' in a) return a.error;
    if (!state.ready) return err(503, 'not_ready', 'The assistant is still preparing.');
    const body = (await request.json()) as AskIn;
    const q = (body.question ?? '').trim();
    if (q.length < 3)
      return err(422, 'question_too_short', 'Ask a question of at least 3 characters.');
    if (q.length > 2000)
      return err(422, 'question_too_long', 'Questions are limited to 2000 characters.');
    if (/\bfail\b/i.test(q))
      return err(
        502,
        'answer_failed',
        'The assistant could not answer right now.',
        'req_demo_5xx_001',
      );
    if (/\bslow\b/i.test(q)) await delay(state.latency ? 6500 : 0);
    else if (state.latency) await delay(state.latency * 6);

    let conv = body.conversation_id
      ? state.conversations.find((c) => c.id === body.conversation_id)
      : undefined;
    if (body.conversation_id && (!conv || state.owners.get(conv.id) !== a.user.id)) {
      return err(404, 'not_found', 'Conversation not found.');
    }
    const now = new Date().toISOString();
    if (!conv) {
      conv = {
        id: nextId('c'),
        title: q.slice(0, 60),
        created_at: now,
        updated_at: now,
        message_count: 0,
        messages: [],
      };
      state.conversations.unshift(conv);
      state.owners.set(conv.id, a.user.id);
    }
    const canned = F.answerFor(q);
    const cached = /\bagain\b/i.test(q) || /\bcached\b/i.test(q);
    const messageId = nextId('m');
    const answer: AnswerOut = {
      request_id: `req_${messageId}`,
      message_id: messageId,
      conversation_id: conv.id,
      ...canned,
      cached,
      cache_similarity: cached ? 0.93 : null,
      matched_question: cached ? 'Is Trulicity preferred under NY Medicaid?' : null,
      provider: cached ? 'cache' : /\bfallback\b/i.test(q) ? 'anthropic' : 'openai',
      model: cached ? null : /\bfallback\b/i.test(q) ? 'claude-sonnet-5-5' : 'gpt-5.5',
      fallback_used: /\bfallback\b/i.test(q),
      latency_seconds: cached ? 0.4 : 7.8,
      created_at: now,
    };
    const msg: MessageOut = { ...answer, question: q, feedback: null };
    conv.messages.push(msg);
    conv.message_count = conv.messages.length;
    conv.updated_at = now;
    state.adminMessages.unshift({
      ...msg,
      user_id: a.user.id,
      user_email: a.user.email,
      agent_status: answer.status === 'answered' ? 'answered' : 'not_found',
      cost_usd: cached ? 0 : 0.021,
      tokens: cached ? {} : { input: 17_800, output: 540 },
      trace_id: cached ? null : `tr_${messageId}`,
    });
    if (cached) state.cache.hits++;
    else state.cache.misses++;
    return HttpResponse.json(answer);
  }),

  http.get(url('/conversations'), async ({ request }) => {
    await wait();
    const a = authenticate(request);
    if ('error' in a) return a.error;
    const mine = state.conversations
      .filter((c) => state.owners.get(c.id) === a.user.id)
      .sort((x, y) => y.updated_at.localeCompare(x.updated_at))
      .map(({ messages: _m, ...summary }) => {
        void _m;
        return summary;
      });
    return HttpResponse.json(page(mine, new URL(request.url).searchParams));
  }),

  http.get(url('/conversations/:id'), async ({ request, params }) => {
    await wait();
    const a = authenticate(request);
    if ('error' in a) return a.error;
    const conv = state.conversations.find((c) => c.id === params.id);
    if (!conv || state.owners.get(conv.id) !== a.user.id)
      return err(404, 'not_found', 'Conversation not found.');
    return HttpResponse.json(conv);
  }),

  http.delete(url('/conversations/:id'), async ({ request, params }) => {
    await wait();
    const a = authenticate(request);
    if ('error' in a) return a.error;
    const i = state.conversations.findIndex((c) => c.id === params.id);
    if (i < 0 || state.owners.get(String(params.id)) !== a.user.id)
      return err(404, 'not_found', 'Conversation not found.');
    state.conversations.splice(i, 1);
    return new HttpResponse(null, { status: 204 });
  }),

  http.post(url('/messages/:id/feedback'), async ({ request, params }) => {
    await wait();
    const a = authenticate(request);
    if ('error' in a) return a.error;
    const body = (await request.json()) as FeedbackIn;
    if (body.rating !== 'helpful' && body.rating !== 'unhelpful')
      return err(422, 'validation_error', 'rating must be helpful or unhelpful.');
    if (body.comment && body.comment.length > 1000)
      return err(422, 'validation_error', 'Comment is limited to 1000 characters.');
    const msg = state.conversations
      .flatMap((c) => c.messages)
      .find((m) => m.message_id === params.id);
    if (!msg) return err(404, 'not_found', 'Message not found.');
    const now = new Date().toISOString();
    const fb: FeedbackOut = {
      message_id: msg.message_id,
      rating: body.rating,
      reason: body.rating === 'unhelpful' ? (body.reason ?? null) : null,
      comment: body.comment ?? null,
      created_at: msg.feedback?.created_at ?? now,
      updated_at: now,
    };
    msg.feedback = fb;
    const am = state.adminMessages.find((m) => m.message_id === msg.message_id);
    if (am) am.feedback = fb;
    return HttpResponse.json(fb);
  }),

  // ---- admin
  http.get(url('/admin/stats'), async ({ request }) => {
    await wait();
    const a = requireAdmin(authenticate(request));
    if ('error' in a) return a.error;
    const days = Number(new URL(request.url).searchParams.get('days') ?? 30) || 30;
    return HttpResponse.json({ ...F.stats(days), cache: { ...state.cache } });
  }),

  http.get(url('/admin/conversations'), async ({ request }) => {
    await wait();
    const a = requireAdmin(authenticate(request));
    if ('error' in a) return a.error;
    const sp = new URL(request.url).searchParams;
    let items = [...state.adminMessages].sort((x, y) => y.created_at.localeCompare(x.created_at));
    const rating = sp.get('rating');
    if (rating) items = items.filter((m) => m.feedback?.rating === rating);
    const status = sp.get('status');
    if (status) items = items.filter((m) => m.status === status);
    const cached = sp.get('cached');
    if (cached) items = items.filter((m) => String(m.cached) === cached);
    const userId = sp.get('user_id');
    if (userId) items = items.filter((m) => m.user_id === userId);
    const q = sp.get('q')?.toLowerCase();
    if (q)
      items = items.filter(
        (m) => m.question.toLowerCase().includes(q) || m.answer.toLowerCase().includes(q),
      );
    const since = sp.get('since');
    if (since) items = items.filter((m) => m.created_at >= since);
    const until = sp.get('until');
    if (until) items = items.filter((m) => m.created_at.slice(0, 10) <= until);
    return HttpResponse.json(page(items, sp));
  }),

  http.get(url('/admin/messages/:id'), async ({ request, params }) => {
    await wait();
    const a = requireAdmin(authenticate(request));
    if ('error' in a) return a.error;
    const m = state.adminMessages.find((x) => x.message_id === params.id);
    if (!m) return err(404, 'not_found', 'Message not found.');
    return HttpResponse.json(m);
  }),

  http.get(url('/admin/documents'), async ({ request }) => {
    await wait();
    const a = requireAdmin(authenticate(request));
    if ('error' in a) return a.error;
    return HttpResponse.json(state.documents);
  }),

  http.post(url('/admin/documents'), async ({ request }) => {
    const a = requireAdmin(authenticate(request));
    if ('error' in a) return a.error;
    const form = await request.formData();
    const file = form.get('file');
    if (!(file instanceof File)) return err(422, 'validation_error', 'A file is required.');
    if (file.size > 50 * 1024 * 1024)
      return err(413, 'upload_too_large', 'Files are limited to 50 MB.');
    const name = file.name.toLowerCase();
    if (!name.endsWith('.pdf') && !name.endsWith('.xlsx'))
      return err(415, 'upload_type', 'Only PDF and XLSX files are accepted.');
    const docId = String(form.get('doc_id') ?? '');
    if (!/^[a-z0-9][a-z0-9_]{1,63}$/.test(docId))
      return err(422, 'validation_error', 'doc_id must be a lowercase slug.');
    if (/\bcorrupt\b/i.test(name))
      return err(422, 'upload_pages', 'The PDF has more than 400 pages or could not be read.');
    await wait();
    const now = new Date().toISOString();
    let doc = state.documents.find((d) => d.id === docId);
    const versionId = nextId('v');
    const version: VersionOut = {
      id: versionId,
      document_id: docId,
      file_name: file.name,
      content_type:
        file.type ||
        (name.endsWith('.pdf')
          ? 'application/pdf'
          : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
      bytes: file.size,
      pages: name.endsWith('.pdf') ? 42 : null,
      status: 'queued',
      error: null,
      chunk_count: 0,
      figure_count: 0,
      created_at: now,
      activated_at: null,
    };
    if (!doc) {
      doc = {
        id: docId,
        title: String(form.get('title') ?? docId),
        program: String(form.get('program') ?? ''),
        doc_type: String(form.get('doc_type') ?? 'other'),
        authority: String(form.get('authority') ?? 'advisory'),
        publisher: String(form.get('publisher') ?? ''),
        doc_date: String(form.get('doc_date') ?? ''),
        source_url: String(form.get('source_url') ?? '') || null,
        active_version: null,
        latest_version: version,
        versions: 1,
      };
      state.documents.push(doc);
    } else {
      doc.latest_version = version;
      doc.versions += 1;
    }
    const job: JobOut = {
      id: nextId('job'),
      version_id: versionId,
      document_id: docId,
      status: 'queued',
      attempt: 1,
      stage: 'queued',
      error: null,
      queued_at: now,
      started_at: null,
      finished_at: null,
    };
    state.jobs.unshift(job);
    const out: UploadOut = { document: doc, version, job, reused: false };
    return HttpResponse.json(out, { status: 202 });
  }),

  http.post(url('/admin/documents/:id/reindex'), async ({ request, params }) => {
    await wait();
    const a = requireAdmin(authenticate(request));
    if ('error' in a) return a.error;
    const doc = state.documents.find((d) => d.id === params.id);
    if (!doc) return err(404, 'not_found', 'Document not found.');
    const now = new Date().toISOString();
    const base = doc.active_version ?? doc.latest_version;
    const version: VersionOut = {
      ...(base ?? {
        file_name: `${doc.id}.pdf`,
        content_type: 'application/pdf',
        bytes: 1_000_000,
        pages: 100,
        chunk_count: 0,
        figure_count: 0,
      }),
      id: nextId('v'),
      document_id: doc.id,
      status: 'queued',
      error: null,
      chunk_count: 0,
      created_at: now,
      activated_at: null,
    };
    doc.latest_version = version;
    doc.versions += 1;
    const job: JobOut = {
      id: nextId('job'),
      version_id: version.id,
      document_id: doc.id,
      status: 'queued',
      attempt: 1,
      stage: 'queued',
      error: null,
      queued_at: now,
      started_at: null,
      finished_at: null,
    };
    state.jobs.unshift(job);
    return HttpResponse.json({ document: doc, version, job, reused: false } satisfies UploadOut, {
      status: 202,
    });
  }),

  http.delete(url('/admin/documents/:id/index'), async ({ request, params }) => {
    await wait();
    const a = requireAdmin(authenticate(request));
    if ('error' in a) return a.error;
    const doc = state.documents.find((d) => d.id === params.id);
    if (!doc) return err(404, 'not_found', 'Document not found.');
    const active = doc.active_version;
    if (!active || active.status !== 'active')
      return err(404, 'not_found', 'The document has no indexed version.');
    if (
      state.jobs.some(
        (j) => j.document_id === doc.id && (j.status === 'queued' || j.status === 'running'),
      )
    )
      return err(409, 'conflict', 'An indexing job for this document is queued or running.');
    const removed: IndexRemovedOut['removed'] = {
      chunks: active.chunk_count,
      parents: Math.ceil(active.chunk_count / 4),
      figures: active.figure_count,
      table_rows: active.content_type.includes('spreadsheet') ? active.chunk_count : 0,
    };
    const superseded: VersionOut = {
      ...active,
      status: 'superseded',
      chunk_count: 0,
      figure_count: 0,
      activated_at: null,
    };
    if (!doc.latest_version || doc.latest_version.id === active.id) doc.latest_version = superseded;
    doc.active_version = null;
    state.generation += 1;
    const out: IndexRemovedOut = { document_id: doc.id, removed, generation: state.generation };
    return HttpResponse.json(out);
  }),

  http.get(url('/admin/jobs'), async ({ request }) => {
    await wait();
    const a = requireAdmin(authenticate(request));
    if ('error' in a) return a.error;
    advanceJobs();
    const sp = new URL(request.url).searchParams;
    let items = [...state.jobs];
    const status = sp.get('status');
    if (status) items = items.filter((j) => j.status === status);
    return HttpResponse.json(page(items, sp));
  }),

  http.get(url('/admin/users'), async ({ request }) => {
    await wait();
    const a = requireAdmin(authenticate(request));
    if ('error' in a) return a.error;
    const sp = new URL(request.url).searchParams;
    const q = sp.get('q')?.toLowerCase();
    let items: UserOut[] = state.users.map(F.publicUser);
    if (q)
      items = items.filter(
        (u) => u.email.toLowerCase().includes(q) || u.display_name.toLowerCase().includes(q),
      );
    return HttpResponse.json(page(items, sp));
  }),

  http.patch(url('/admin/users/:id'), async ({ request, params }) => {
    await wait();
    const a = requireAdmin(authenticate(request));
    if ('error' in a) return a.error;
    const user = state.users.find((u) => u.id === params.id);
    if (!user) return err(404, 'not_found', 'User not found.');
    const body = (await request.json()) as UserPatchIn;
    if (user.id === a.user.id && (body.role === 'staff' || body.is_active === false)) {
      return err(422, 'validation_error', 'You cannot demote or deactivate your own account.');
    }
    if (body.role) user.role = body.role;
    if (typeof body.is_active === 'boolean') user.is_active = body.is_active;
    if (typeof body.display_name === 'string') user.display_name = body.display_name;
    return HttpResponse.json(F.publicUser(user));
  }),

  http.get(url('/admin/cache/stats'), async ({ request }) => {
    await wait();
    const a = requireAdmin(authenticate(request));
    if ('error' in a) return a.error;
    const total = state.cache.hits + state.cache.misses;
    return HttpResponse.json({ ...state.cache, hit_rate: total ? state.cache.hits / total : 0 });
  }),

  http.delete(url('/admin/cache'), async ({ request }) => {
    await wait();
    const a = requireAdmin(authenticate(request));
    if ('error' in a) return a.error;
    state.cache = {
      ...state.cache,
      entries: 0,
      hits: 0,
      misses: 0,
      cleared_at: new Date().toISOString(),
      hit_rate: 0,
      generation: (state.cache.generation ?? 0) + 1,
    };
    return new HttpResponse(null, { status: 204 });
  }),

  // ---- sources and figures: a tiny placeholder so links and thumbnails resolve in mock mode
  http.get(url('/figures/:doc/:name'), async () => {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="200"><rect width="320" height="200" fill="#eef2f6"/><rect x="20" y="24" width="120" height="36" rx="6" fill="#0f766e"/><rect x="180" y="24" width="120" height="36" rx="6" fill="#0f766e" opacity=".6"/><rect x="100" y="110" width="120" height="36" rx="6" fill="#0f766e" opacity=".8"/><path d="M80 60v30h80M240 60v30h-60M160 90v20" stroke="#5a6982" stroke-width="2" fill="none"/></svg>`;
    return new HttpResponse(svg, { headers: { 'Content-Type': 'image/svg+xml' } });
  }),
  http.get(url('/sources/:doc/:page'), async () => {
    return new HttpResponse('Mock mode: the real API redirects to a presigned PDF page.', {
      headers: { 'Content-Type': 'text/plain' },
    });
  }),
];
