import { useRef } from 'react';
import { Copy } from 'lucide-react';
import type { AdminMessageOut } from '@/api/types';
import { useAdminMessage } from '@/api/queries';
import { AnswerBadges } from '@/components/ask/AnswerBadges';
import { CitationList } from '@/components/ask/CitationList';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { useToast } from '@/components/ui/toast';
import { AnswerMarkdown } from '@/lib/markdown';
import { FEEDBACK_REASONS } from '@/lib/constants';
import { formatDateTime, formatSeconds, formatUsd } from '@/lib/format';

export function MessageDrawer({
  messageId,
  initial,
  onClose,
}: {
  messageId: string | null;
  initial: AdminMessageOut | null;
  onClose: () => void;
}) {
  const query = useAdminMessage(messageId);
  const m = query.data ?? initial;
  const { toast } = useToast();
  const contentRef = useRef<HTMLDivElement>(null);

  async function copy(text: string, what: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast({ kind: 'default', title: `${what} copied` });
    } catch {
      toast({ kind: 'error', title: `Could not copy the ${what.toLowerCase()}` });
    }
  }

  return (
    <Sheet open={!!messageId} onOpenChange={(o) => !o && onClose()}>
      <SheetContent
        ref={contentRef}
        className="sm:max-w-2xl"
        onOpenAutoFocus={(e) => {
          // focus the panel itself, not the first badge (whose tooltip would open)
          e.preventDefault();
          contentRef.current?.focus();
        }}
      >
        {!m ? (
          <div className="grid gap-3" aria-busy="true">
            <Skeleton className="h-6 w-2/3" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : (
          <>
            <SheetHeader>
              <SheetTitle className="pr-6 text-base">{m.question}</SheetTitle>
              <SheetDescription>
                {m.user_email} · {formatDateTime(m.created_at)}
              </SheetDescription>
            </SheetHeader>

            <div className="flex flex-wrap items-center gap-1.5">
              {m.status === 'no_answer' ? (
                <Badge variant="muted">No answer</Badge>
              ) : (
                <Badge variant="success">Answered</Badge>
              )}
              <AnswerBadges answer={m} />
              {m.agent_status ? <Badge variant="outline">agent: {m.agent_status}</Badge> : null}
            </div>

            {m.assumption ? (
              <p className="rounded-md border border-amber-border bg-amber-bg px-3 py-2 text-sm text-amber">
                <span className="font-semibold">Assumption: </span>
                {m.assumption}
              </p>
            ) : null}

            <section aria-labelledby="drawer-answer">
              <h3
                id="drawer-answer"
                className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground"
              >
                Answer
              </h3>
              <AnswerMarkdown className="answer-body rounded-md border bg-muted/30 p-3 text-sm">
                {m.answer}
              </AnswerMarkdown>
              {m.conflicts_noted.length ? (
                <ul className="mt-2 list-disc pl-5 text-sm text-muted-foreground">
                  {m.conflicts_noted.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              ) : null}
            </section>

            <section aria-labelledby="drawer-citations">
              <h3
                id="drawer-citations"
                className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground"
              >
                Citations ({m.citations.length})
              </h3>
              <CitationList citations={m.citations} compact />
            </section>

            <section aria-labelledby="drawer-feedback">
              <h3
                id="drawer-feedback"
                className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground"
              >
                Feedback
              </h3>
              {m.feedback ? (
                <div className="rounded-md border p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={m.feedback.rating === 'helpful' ? 'success' : 'destructive'}>
                      {m.feedback.rating === 'helpful' ? 'Helpful' : 'Unhelpful'}
                    </Badge>
                    {m.feedback.reason ? (
                      <span className="text-muted-foreground">
                        Reason:{' '}
                        {FEEDBACK_REASONS.find((r) => r.value === m.feedback?.reason)?.label ??
                          m.feedback.reason}
                      </span>
                    ) : null}
                    <span className="ml-auto text-xs text-muted-foreground">
                      {formatDateTime(m.feedback.updated_at)}
                    </span>
                  </div>
                  {m.feedback.comment ? (
                    <p className="mt-2 whitespace-pre-wrap">{m.feedback.comment}</p>
                  ) : null}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">No rating yet.</p>
              )}
            </section>

            <section aria-labelledby="drawer-meta">
              <h3
                id="drawer-meta"
                className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground"
              >
                Details
              </h3>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                <Dt>Provider / model</Dt>
                <Dd>
                  {m.provider ?? '–'} / {m.model ?? '–'}
                  {m.fallback_used ? ' (fallback)' : ''}
                </Dd>
                <Dt>Cached</Dt>
                <Dd>
                  {m.cached ? 'yes' : 'no'}
                  {m.cached && m.cache_similarity != null
                    ? ` (similarity ${m.cache_similarity.toFixed(2)})`
                    : ''}
                  {m.cached && m.matched_question ? ` · matched "${m.matched_question}"` : ''}
                </Dd>
                <Dt>Latency</Dt>
                <Dd>{formatSeconds(m.latency_seconds, 2)}</Dd>
                <Dt>Cost</Dt>
                <Dd>{m.cost_usd != null ? formatUsd(m.cost_usd, 4) : '–'}</Dd>
                <Dt>Tokens</Dt>
                <Dd>
                  {Object.keys(m.tokens).length
                    ? Object.entries(m.tokens)
                        .map(([k, v]) => `${k} ${v.toLocaleString()}`)
                        .join(' · ')
                    : '–'}
                </Dd>
                <Dt>Needs review</Dt>
                <Dd>{m.needs_review ? 'yes' : 'no'}</Dd>
                <Dt>Request id</Dt>
                <Dd>
                  <span className="inline-flex items-center gap-1 font-mono text-xs">
                    {m.request_id}
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Copy request id"
                      onClick={() => void copy(m.request_id, 'Request id')}
                    >
                      <Copy />
                    </Button>
                  </span>
                </Dd>
                <Dt>Message id</Dt>
                <Dd className="font-mono text-xs">{m.message_id}</Dd>
                <Dt>Conversation</Dt>
                <Dd className="font-mono text-xs">{m.conversation_id}</Dd>
                {m.trace_id ? (
                  <>
                    <Dt>Trace id</Dt>
                    <Dd className="font-mono text-xs">{m.trace_id}</Dd>
                  </>
                ) : null}
                <Dt>User id</Dt>
                <Dd className="font-mono text-xs">{m.user_id}</Dd>
              </dl>
            </section>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

function Dt({ children }: { children: React.ReactNode }) {
  return <dt className="text-muted-foreground">{children}</dt>;
}
function Dd({ children, className }: { children: React.ReactNode; className?: string }) {
  return <dd className={className}>{children}</dd>;
}
