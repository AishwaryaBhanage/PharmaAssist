import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react';
import { ArrowUp, Square } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { EXAMPLE_QUESTIONS, LOADING_MESSAGES, MAX_QUESTION, MIN_QUESTION } from '@/lib/constants';
import { cn } from '@/lib/utils';

export function canSubmit(text: string, ready: boolean, pending: boolean): boolean {
  const n = text.trim().length;
  return ready && !pending && n >= MIN_QUESTION && n <= MAX_QUESTION;
}

export function Composer({
  value,
  onChange,
  onSubmit,
  onCancel,
  pending,
  ready,
  showExamples,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
  pending: boolean;
  ready: boolean;
  showExamples?: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const n = value.length;
  const over = value.trim().length > MAX_QUESTION;
  const ok = canSubmit(value, ready, pending);

  useEffect(() => {
    if (!pending) ref.current?.focus();
  }, [pending]);

  // Two rows by default; grows with the draft until the CSS max-height (about six rows),
  // after which the textarea scrolls on its own.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    if (el.scrollHeight)
      el.style.height = `${el.scrollHeight + el.offsetHeight - el.clientHeight}px`;
  }, [value]);

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (ok) onSubmit();
    }
  }

  return (
    <div className="grid gap-3">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (ok) onSubmit();
        }}
        className={cn(
          'rounded-xl border bg-card shadow-xs transition-[border-color,box-shadow] focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/20',
          over &&
            'border-destructive focus-within:border-destructive focus-within:ring-destructive/20',
          pending && 'border-dashed',
        )}
      >
        <label htmlFor="question" className="sr-only">
          Question
        </label>
        <Textarea
          id="question"
          ref={ref}
          rows={2}
          value={value}
          disabled={pending}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask a policy or formulary question…"
          aria-describedby="question-hint question-counter"
          maxLength={MAX_QUESTION + 200}
          className="max-h-40 min-h-0 resize-none overflow-y-auto rounded-xl border-0 bg-transparent px-4 pb-1 pt-3 text-[15px] leading-normal shadow-none focus-visible:outline-0 disabled:opacity-70"
        />
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 px-3 pb-2.5 pt-1 sm:flex-nowrap">
          <p
            id="question-hint"
            className={cn(
              'min-w-0 basis-full pl-1 text-xs leading-snug text-muted-foreground sm:basis-auto',
              pending && 'hidden',
            )}
          >
            <span className="hidden sm:inline">
              <kbd className="rounded border bg-muted px-1 font-sans text-[10px]">Enter</kbd> sends
              ·{' '}
              <kbd className="rounded border bg-muted px-1 font-sans text-[10px]">Shift+Enter</kbd>{' '}
              adds a line ·{' '}
            </span>
            Cites only the loaded VA, Medicare Part D and NY Medicaid documents. No patient
            information.
          </p>
          {pending ? <PendingIndicator className="pl-1" /> : null}
          <div className="ml-auto flex shrink-0 items-center gap-3">
            <span
              id="question-counter"
              aria-live="polite"
              className={cn(
                'text-xs tabular-nums text-muted-foreground',
                over && 'font-semibold text-destructive',
              )}
            >
              {n} / {MAX_QUESTION}
            </span>
            {pending ? (
              <Button type="button" variant="outline" size="sm" onClick={onCancel}>
                <Square />
                Cancel
              </Button>
            ) : (
              <Button type="submit" size="sm" disabled={!ok} className="h-9 gap-1.5 px-4 shadow-xs">
                Ask
                <ArrowUp strokeWidth={2.5} />
              </Button>
            )}
          </div>
        </div>
      </form>
      {showExamples && !pending ? (
        <ExampleQuestions
          onPick={(q) => {
            onChange(q);
            ref.current?.focus();
          }}
        />
      ) : null}
    </div>
  );
}

/** Example questions as chips; picking one fills the composer. */
export function ExampleQuestions({
  onPick,
  className,
}: {
  onPick: (q: string) => void;
  className?: string;
}) {
  return (
    <div
      className={cn('flex flex-wrap gap-2', className)}
      role="group"
      aria-label="Example questions"
    >
      {EXAMPLE_QUESTIONS.map((q) => (
        <button
          key={q}
          type="button"
          onClick={() => onPick(q)}
          className="rounded-full border bg-card px-4 py-2 text-sm text-secondary-foreground shadow-xs transition-[color,background-color,border-color,transform] hover:-translate-y-px hover:border-primary/50 hover:bg-accent hover:text-accent-foreground focus-visible:outline-2 focus-visible:outline-ring active:translate-y-0"
        >
          {q}
        </button>
      ))}
    </div>
  );
}

/** Elapsed seconds plus the rotating v1 loading messages (every 3 s). */
export function PendingIndicator({ className }: { className?: string } = {}) {
  const [elapsed, setElapsed] = useState(0);
  const [i, setI] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const t1 = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    const t2 = setInterval(() => setI((v) => (v + 1) % LOADING_MESSAGES.length), 3000);
    return () => {
      clearInterval(t1);
      clearInterval(t2);
    };
  }, []);
  return (
    <div className={cn('flex min-w-0 items-center gap-2 text-xs', className)}>
      <span
        aria-hidden="true"
        className="size-3.5 shrink-0 animate-spin rounded-full border-2 border-accent border-t-primary"
      />
      <p
        role="status"
        aria-live="polite"
        className="truncate font-medium text-secondary-foreground"
      >
        {LOADING_MESSAGES[i]}
      </p>
      <p className="shrink-0 tabular-nums text-muted-foreground" aria-label="Elapsed time">
        {elapsed} s
      </p>
    </div>
  );
}
