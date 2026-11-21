import { useEffect, useRef } from 'react';
import type { FeedbackIn, MessageOut } from '@/api/types';
import { Skeleton } from '@/components/ui/skeleton';
import { relativeTime } from '@/lib/format';
import { AnswerCard } from './AnswerCard';
import { PendingIndicator } from './Composer';

export function QuestionBubble({ question, at }: { question: string; at?: string }) {
  return (
    <div className="flex flex-col items-end gap-1">
      <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-[15px] leading-relaxed text-primary-foreground shadow-xs">
        {question}
      </p>
      {at ? (
        <span className="pr-1 text-[11px] text-muted-foreground">{relativeTime(at)}</span>
      ) : null}
    </div>
  );
}

/** Placeholder for an answer. With `live`, the same progress line as the composer (current step,
 * elapsed seconds) sits on top, so the thread shows what is happening instead of blank bars. */
export function AnswerSkeleton({ live }: { live?: boolean }) {
  return (
    <div className="rounded-xl border bg-card p-4 shadow-xs" aria-hidden={live ? undefined : true}>
      {live ? <PendingIndicator className="mb-4 text-sm" /> : null}
      <Skeleton className="h-4 w-11/12" />
      <Skeleton className="mt-2 h-4 w-10/12" />
      <Skeleton className="mt-2 h-4 w-7/12" />
      <Skeleton className="mt-4 h-3 w-1/3" />
    </div>
  );
}

export function Thread({
  messages,
  pendingQuestion,
  onFeedback,
  feedbackPendingId,
}: {
  messages: MessageOut[];
  pendingQuestion: string | null;
  onFeedback: (messageId: string, body: FeedbackIn) => void;
  feedbackPendingId: string | null;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  const count = messages.length + (pendingQuestion ? 1 : 0);
  // Keep the latest message in view inside the scrolling thread column.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' });
  }, [count]);

  return (
    <div className="grid gap-6">
      {messages.map((m) => (
        <div key={m.message_id} className="grid gap-2">
          <QuestionBubble question={m.question} at={m.created_at} />
          <AnswerCard
            message={m}
            onFeedback={(body) => onFeedback(m.message_id, body)}
            feedbackPending={feedbackPendingId === m.message_id}
          />
        </div>
      ))}
      {pendingQuestion ? (
        <div className="grid gap-2">
          <QuestionBubble question={pendingQuestion} />
          <AnswerSkeleton live />
        </div>
      ) : null}
      <div ref={endRef} />
    </div>
  );
}
