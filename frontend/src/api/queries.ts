import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { admin, ask, health } from './endpoints';
import type {
  AdminConversationsParams,
  AdminJobsParams,
  AdminUsersParams,
  AnswerOut,
  AskIn,
  ConversationOut,
  FeedbackIn,
  FeedbackOut,
  MessageOut,
  Page,
  UserPatchIn,
} from './types';

export const keys = {
  conversations: ['conversations'] as const,
  conversation: (id: string) => ['conversations', id] as const,
  health: ['health'] as const,
  adminStats: (days: number) => ['admin', 'stats', days] as const,
  adminConversations: (p: AdminConversationsParams) => ['admin', 'conversations', p] as const,
  adminMessage: (id: string) => ['admin', 'messages', id] as const,
  adminDocuments: ['admin', 'documents'] as const,
  adminJobs: (p: AdminJobsParams) => ['admin', 'jobs', p] as const,
  adminUsers: (p: AdminUsersParams) => ['admin', 'users', p] as const,
  adminCache: ['admin', 'cache'] as const,
};

// ---------------------------------------------------------------- health

export function useReadiness() {
  return useQuery({
    queryKey: keys.health,
    queryFn: health.ready,
    refetchInterval: (q) => (q.state.data?.ready ? false : 3000),
    retry: false,
  });
}

// ---------------------------------------------------------------- ask

export function useConversations() {
  return useQuery({
    queryKey: keys.conversations,
    queryFn: () => ask.conversations({ limit: 100 }),
  });
}

export function useConversation(id: string | null) {
  return useQuery({
    queryKey: keys.conversation(id ?? ''),
    queryFn: () => ask.conversation(id!),
    enabled: !!id,
  });
}

export function useAsk() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ body, signal }: { body: AskIn; signal?: AbortSignal }) =>
      ask.submit(body, signal),
    onSuccess: (answer: AnswerOut, { body }) => {
      // Append to the conversation thread without a refetch; the list refreshes for titles/times.
      const message: MessageOut = { ...answer, question: body.question, feedback: null };
      qc.setQueryData<ConversationOut>(keys.conversation(answer.conversation_id), (prev) =>
        prev
          ? {
              ...prev,
              updated_at: answer.created_at,
              message_count: prev.message_count + 1,
              messages: [...prev.messages, message],
            }
          : {
              id: answer.conversation_id,
              title: body.question.slice(0, 60),
              created_at: answer.created_at,
              updated_at: answer.created_at,
              message_count: 1,
              messages: [message],
            },
      );
      void qc.invalidateQueries({ queryKey: keys.conversations });
    },
  });
}

export function useDeleteConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => ask.deleteConversation(id),
    onSuccess: (_d, id) => {
      qc.removeQueries({ queryKey: keys.conversation(id) });
      void qc.invalidateQueries({ queryKey: keys.conversations });
    },
  });
}

export function useFeedback(conversationId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ messageId, body }: { messageId: string; body: FeedbackIn }) =>
      ask.feedback(messageId, body),
    onSuccess: (fb: FeedbackOut) => {
      qc.setQueryData<ConversationOut>(keys.conversation(conversationId), (prev) =>
        prev
          ? {
              ...prev,
              messages: prev.messages.map((m) =>
                m.message_id === fb.message_id ? { ...m, feedback: fb } : m,
              ),
            }
          : prev,
      );
    },
  });
}

// ---------------------------------------------------------------- admin

export function useAdminStats(days = 30) {
  return useQuery({ queryKey: keys.adminStats(days), queryFn: () => admin.stats(days) });
}

export function useAdminConversations(p: AdminConversationsParams) {
  return useQuery({
    queryKey: keys.adminConversations(p),
    queryFn: () => admin.conversations(p),
    placeholderData: keepPreviousData,
  });
}

export function useAdminMessage(id: string | null) {
  return useQuery({
    queryKey: keys.adminMessage(id ?? ''),
    queryFn: () => admin.message(id!),
    enabled: !!id,
  });
}

export function useAdminDocuments() {
  return useQuery({ queryKey: keys.adminDocuments, queryFn: admin.documents });
}

const LIVE_JOB = new Set([
  'queued',
  'running',
  'parsing',
  'extracting_figures',
  'chunking',
  'embedding',
  'verifying',
]);

const TERMINAL_JOB = new Set(['failed', 'active', 'done', 'superseded', 'cancelled']);

/** Queued or running. A finished job keeps the stage it stopped at, so the status wins. */
export function isLiveJob(status: string | null | undefined, stage?: string | null): boolean {
  if (TERMINAL_JOB.has(status ?? '')) return false;
  return LIVE_JOB.has(status ?? '') || LIVE_JOB.has(stage ?? '');
}

export function useAdminJobs(p: AdminJobsParams = {}) {
  return useQuery({
    queryKey: keys.adminJobs(p),
    queryFn: () => admin.jobs(p),
    refetchInterval: (q) => {
      const items = (q.state.data as Page<{ status: string; stage?: string | null }> | undefined)
        ?.items;
      return items?.some((j) => isLiveJob(j.status, j.stage)) ? 5000 : false;
    },
  });
}

export function useReindex() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => admin.reindex(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.adminDocuments });
      void qc.invalidateQueries({ queryKey: ['admin', 'jobs'] });
    },
  });
}

export function useRemoveFromIndex() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => admin.removeFromIndex(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.adminDocuments });
      void qc.invalidateQueries({ queryKey: ['admin', 'jobs'] });
      void qc.invalidateQueries({ queryKey: ['admin', 'stats'] });
    },
  });
}

export function useAdminUsers(p: AdminUsersParams) {
  return useQuery({
    queryKey: keys.adminUsers(p),
    queryFn: () => admin.users(p),
    placeholderData: keepPreviousData,
  });
}

export function usePatchUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: UserPatchIn }) => admin.patchUser(id, body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['admin', 'users'] }),
  });
}

export function useCacheStats() {
  return useQuery({ queryKey: keys.adminCache, queryFn: admin.cacheStats });
}

export function useClearCache() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: admin.clearCache,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.adminCache });
      void qc.invalidateQueries({ queryKey: ['admin', 'stats'] });
      void qc.invalidateQueries({ queryKey: ['admin', 'stats'] });
    },
  });
}
