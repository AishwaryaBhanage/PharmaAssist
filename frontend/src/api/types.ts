/**
 * Wire types for /api/v1, hand-written from app/api/schemas.py.
 * Field names are the wire format. Regenerate with `npm run gen:types` once the backend exports
 * frontend/openapi.json; `generated.d.ts` then becomes the source and this file should be checked
 * against it.
 */

export type Role = 'staff' | 'admin';

export const NO_ANSWER_TEXT = 'No answer found in knowledge base';

/** Error codes the frontend handles by name (schemas.py docstring). */
export type ErrorCode =
  | 'unauthenticated'
  | 'invalid_credentials'
  | 'forbidden'
  | 'token_expired'
  | 'signup_disabled'
  | 'email_taken'
  | 'weak_password'
  | 'question_too_short'
  | 'question_too_long'
  | 'rate_limited'
  | 'daily_limit'
  | 'spend_cap'
  | 'not_ready'
  | 'timeout'
  | 'answer_failed'
  | 'not_found'
  | 'upload_too_large'
  | 'upload_type'
  | 'upload_pages'
  | 'duplicate_version'
  | 'conflict'
  | 'validation_error';

export interface ErrorOut {
  code: ErrorCode | (string & {});
  message: string;
  request_id?: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

// ---------------------------------------------------------------- auth

export interface SignupIn {
  email: string;
  password: string;
  display_name?: string;
}

export interface LoginIn {
  email: string;
  password: string;
}

export interface UserOut {
  id: string;
  email: string;
  display_name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
  last_login_at?: string | null;
}

export interface TokenOut {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
  user: UserOut;
}

// ---------------------------------------------------------------- ask

export interface AskIn {
  question: string;
  conversation_id?: string | null;
}

export type FigureStatus = 'machine_interpreted' | 'ocr_checked' | 'reviewed';

export interface FigureOut {
  figure_id: string;
  kind?: string | null;
  title?: string | null;
  status: FigureStatus | (string & {});
  status_text: string;
  crop_url?: string | null;
}

export interface CitationOut {
  id: string;
  doc_id: string;
  document: string;
  label: string;
  page?: number | null;
  sheet?: string | null;
  row?: number | null;
  url?: string | null;
  local_url?: string | null;
  flagged: boolean;
  flag_reason?: string | null;
  figures: FigureOut[];
}

export type AnswerStatus = 'answered' | 'no_answer';

export interface AnswerOut {
  request_id: string;
  message_id: string;
  conversation_id: string;
  status: AnswerStatus;
  answer: string;
  assumption?: string | null;
  citations: CitationOut[];
  conflicts_noted: string[];
  needs_review: boolean;
  cached: boolean;
  cache_similarity?: number | null;
  matched_question?: string | null;
  provider?: string | null;
  model?: string | null;
  fallback_used: boolean;
  latency_seconds?: number | null;
  created_at: string;
}

export type FeedbackRating = 'helpful' | 'unhelpful';
export type FeedbackReason = 'wrong' | 'incomplete' | 'outdated' | 'unclear' | 'other';

export interface FeedbackIn {
  rating: FeedbackRating;
  reason?: FeedbackReason | null;
  comment?: string | null;
}

export interface FeedbackOut {
  message_id: string;
  rating: FeedbackRating;
  reason?: string | null;
  comment?: string | null;
  created_at: string;
  updated_at: string;
}

export interface MessageOut extends AnswerOut {
  question: string;
  feedback?: FeedbackOut | null;
}

export interface ConversationSummaryOut {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ConversationOut extends ConversationSummaryOut {
  messages: MessageOut[];
}

// ---------------------------------------------------------------- admin

export interface AdminMessageOut extends MessageOut {
  user_id: string;
  user_email: string;
  agent_status?: string | null;
  cost_usd?: number | null;
  tokens: Record<string, number>;
  trace_id?: string | null;
}

export interface DayStatOut {
  day: string;
  questions: number;
  helpful: number;
  unhelpful: number;
  no_answer: number;
  cached: number;
}

export interface StatsOut {
  since: string;
  until: string;
  questions: number;
  answered: number;
  no_answer: number;
  cached: number;
  fallback: number;
  helpful: number;
  unhelpful: number;
  latency_p50_s?: number | null;
  latency_p95_s?: number | null;
  spend_usd: number;
  spend_cap_usd: number;
  spend_today_usd: number;
  active_users: number;
  users_total: number;
  documents_active: number;
  cache: Record<string, unknown>;
  per_day: DayStatOut[];
}

export type VersionStatus =
  | 'queued'
  | 'parsing'
  | 'extracting_figures'
  | 'chunking'
  | 'embedding'
  | 'verifying'
  | 'active'
  | 'failed'
  | 'superseded';

export interface VersionOut {
  id: string;
  document_id: string;
  file_name: string;
  content_type: string;
  bytes: number;
  pages?: number | null;
  status: VersionStatus | (string & {});
  error?: string | null;
  chunk_count: number;
  figure_count: number;
  created_at?: string | null;
  activated_at?: string | null;
}

export interface DocumentOut {
  id: string;
  title: string;
  program: string;
  doc_type: string;
  authority: string;
  publisher: string;
  doc_date: string;
  source_url?: string | null;
  active_version?: VersionOut | null;
  latest_version?: VersionOut | null;
  versions: number;
}

export interface JobOut {
  id: string;
  version_id: string;
  document_id: string;
  document_title?: string | null;
  status: string;
  attempt: number;
  stage?: string | null;
  error?: string | null;
  queued_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface UploadOut {
  document: DocumentOut;
  version: VersionOut;
  job?: JobOut | null;
  reused: boolean;
}

/** DELETE /admin/documents/{id}/index: the active version's index rows are gone, the file stays. */
export interface IndexRemovedOut {
  document_id: string;
  removed: { chunks: number; parents: number; figures: number; table_rows: number };
  generation: number;
}

export interface UserPatchIn {
  role?: Role | null;
  is_active?: boolean | null;
  display_name?: string | null;
}

export interface CacheStatsOut {
  entries: number;
  hits: number;
  misses: number;
  hit_rate: number;
  threshold?: number | null;
  generation?: number | null;
  backend: string;
  cleared_at?: string | null;
}

export interface CacheClearOut {
  removed: number;
}

// ---------------------------------------------------------------- health

export interface HealthOut {
  ready: boolean;
  checks: Record<string, boolean>;
  version?: string | null;
  generation?: number | null;
}

// ---------------------------------------------------------------- query params (not in schemas.py)

export interface PageParams {
  offset?: number;
  limit?: number;
}

export interface AdminConversationsParams extends PageParams {
  rating?: FeedbackRating;
  status?: AnswerStatus;
  user_id?: string;
  q?: string;
  cached?: boolean;
  since?: string;
  until?: string;
}

export interface AdminJobsParams extends PageParams {
  status?: string;
}

export interface AdminUsersParams extends PageParams {
  q?: string;
}

export interface UploadFields {
  doc_id: string;
  title: string;
  program: string;
  doc_type: string;
  authority: string;
  publisher: string;
  doc_date: string;
  source_url: string;
}
