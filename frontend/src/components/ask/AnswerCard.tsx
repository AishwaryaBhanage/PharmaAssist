import { Info, SearchX } from 'lucide-react';
import type { FeedbackIn, MessageOut } from '@/api/types';
import { NO_ANSWER_TEXT } from '@/api/types';
import { AnswerMarkdown } from '@/lib/markdown';
import { REVIEW_WARNING } from '@/lib/constants';
import { formatSeconds } from '@/lib/format';
import { AnswerBadges } from './AnswerBadges';
import { CitationList } from './CitationList';
import { FeedbackBar } from './FeedbackBar';

export function isNoAnswer(m: Pick<MessageOut, 'status' | 'answer'>): boolean {
  return m.status === 'no_answer' || m.answer.trim() === NO_ANSWER_TEXT;
}

export function AnswerCard({
  message,
  onFeedback,
  feedbackPending,
}: {
  message: MessageOut;
  onFeedback?: (body: FeedbackIn) => void;
  feedbackPending?: boolean;
}) {
  const footer = [
    message.provider && message.provider !== 'cache' ? message.provider : null,
    message.model,
    formatSeconds(message.latency_seconds),
  ]
    .filter(Boolean)
    .join(' · ');

  if (isNoAnswer(message)) {
    return (
      <article className="rounded-xl border bg-card px-5 py-4 shadow-xs" aria-label="Answer">
        <div className="flex flex-col items-center gap-2 py-4 text-center">
          <span className="flex size-10 items-center justify-center rounded-full bg-muted text-muted-foreground">
            <SearchX className="size-5" aria-hidden="true" />
          </span>
          <p className="font-medium">{NO_ANSWER_TEXT}</p>
          <p className="max-w-md text-sm text-muted-foreground">
            The loaded documents do not cover this. Try naming the program (VA, Medicare Part D, NY
            Medicaid) or the drug and dosage form, or check the source documents directly.
          </p>
        </div>
        <Footer text={footer} badges={<AnswerBadges answer={message} />} />
        {onFeedback ? (
          <div className="mt-3 border-t pt-3">
            <FeedbackBar
              messageId={message.message_id}
              saved={message.feedback}
              onSubmit={onFeedback}
              pending={!!feedbackPending}
            />
          </div>
        ) : null}
      </article>
    );
  }

  return (
    <article className="rounded-xl border bg-card px-5 py-4 shadow-xs" aria-label="Answer">
      {message.assumption ? (
        <p className="mb-2.5 flex items-start gap-2 rounded-md border border-amber-border bg-amber-bg px-2.5 py-1.5 text-[13px] leading-snug text-amber">
          <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          <span>
            <span className="font-semibold">Assumption: </span>
            {message.assumption}
          </span>
        </p>
      ) : null}
      {message.needs_review ? (
        <p className="mb-2.5 rounded-md border border-amber-border bg-amber-bg px-2.5 py-1.5 text-[13px] font-medium leading-snug text-amber">
          {REVIEW_WARNING}
        </p>
      ) : null}

      <AnswerMarkdown className="answer-body text-[15px] leading-relaxed">
        {message.answer}
      </AnswerMarkdown>

      {message.conflicts_noted.length ? (
        <div className="mt-2.5 rounded-md border bg-muted/50 px-2.5 py-1.5 text-[13px]">
          <p className="font-semibold text-secondary-foreground">Conflicts noted</p>
          <ul className="mt-0.5 list-disc pl-5 text-muted-foreground">
            {message.conflicts_noted.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <Footer text={footer} badges={<AnswerBadges answer={message} />} />

      <section className="mt-3 border-t pt-3" aria-labelledby={`citations-${message.message_id}`}>
        <h3
          id={`citations-${message.message_id}`}
          className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
        >
          Citations {message.citations.length ? `(${message.citations.length})` : ''}
        </h3>
        <CitationList citations={message.citations} />
      </section>

      {onFeedback ? (
        <div className="mt-3 border-t pt-3">
          <FeedbackBar
            messageId={message.message_id}
            saved={message.feedback}
            onSubmit={onFeedback}
            pending={!!feedbackPending}
          />
        </div>
      ) : null}
    </article>
  );
}

function Footer({ text, badges }: { text: string; badges: React.ReactNode }) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      {badges}
      {text ? <span className="ml-auto tabular-nums">{text}</span> : null}
    </div>
  );
}
