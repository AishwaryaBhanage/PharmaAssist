import { isApiError } from '@/api/client';
import { useToast } from '@/components/ui/toast';
import { useCallback } from 'react';

const FRIENDLY: Record<string, string> = {
  network: 'Could not reach the server. Check your connection and try again.',
  timeout: 'The assistant took too long to answer. Please try again.',
  not_ready: 'The assistant is still preparing. Please try again in a moment.',
  rate_limited: 'You are asking too quickly. Please wait a moment.',
  daily_limit: 'The daily question limit has been reached.',
  spend_cap: 'The daily spend cap has been reached; questions resume tomorrow.',
  answer_failed: 'The assistant could not answer right now. Please try again.',
  forbidden: 'You do not have access to this.',
};

/** Short, user-facing text for any thrown value. Server messages are shown when present. */
export function describeError(e: unknown): {
  message: string;
  requestId: string | null;
  serverError: boolean;
} {
  if (isApiError(e)) {
    const message = e.message || FRIENDLY[e.code] || 'Something went wrong. Please try again.';
    return { message, requestId: e.requestId, serverError: e.isServerError };
  }
  if (e instanceof DOMException && e.name === 'AbortError') {
    return { message: 'Cancelled.', requestId: null, serverError: false };
  }
  return {
    message: 'Something went wrong. Please try again.',
    requestId: null,
    serverError: false,
  };
}

export function errorCode(e: unknown): string | null {
  return isApiError(e) ? e.code : null;
}

async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    /* clipboard unavailable: nothing else to do */
  }
}

/** Toasts an error; 5xx responses get a "Copy request id" action. */
export function useErrorToast(): (e: unknown, title?: string) => void {
  const { toast } = useToast();
  return useCallback(
    (e: unknown, title = 'Request failed') => {
      const { message, requestId, serverError } = describeError(e);
      toast({
        kind: 'error',
        title,
        description: message,
        action:
          serverError && requestId
            ? {
                label: `Copy request id ${requestId.slice(0, 8)}…`,
                onClick: () => void copyText(requestId),
              }
            : undefined,
      });
    },
    [toast],
  );
}
