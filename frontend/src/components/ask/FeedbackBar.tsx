import { useState } from 'react';
import { Check, ThumbsDown, ThumbsUp } from 'lucide-react';
import type { FeedbackIn, FeedbackOut, FeedbackReason } from '@/api/types';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { FEEDBACK_REASONS, MAX_COMMENT } from '@/lib/constants';
import { cn } from '@/lib/utils';

export function FeedbackBar({
  messageId,
  saved,
  onSubmit,
  pending,
}: {
  messageId: string;
  saved: FeedbackOut | null | undefined;
  onSubmit: (body: FeedbackIn) => void;
  pending: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<FeedbackReason | ''>('');
  const [comment, setComment] = useState('');
  const commentOver = comment.length > MAX_COMMENT;

  function sendDown() {
    if (commentOver) return;
    onSubmit({ rating: 'unhelpful', reason: reason || null, comment: comment.trim() || null });
    setOpen(false);
  }

  const reasonLabel = saved?.reason
    ? FEEDBACK_REASONS.find((r) => r.value === saved.reason)?.label
    : null;

  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">Was this helpful?</span>
        <div className="flex gap-1" role="group" aria-label="Rate this answer">
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-pressed={saved?.rating === 'helpful'}
            disabled={pending}
            onClick={() => {
              setOpen(false);
              onSubmit({ rating: 'helpful' });
            }}
            className={cn(
              saved?.rating === 'helpful' && 'border-primary bg-accent text-accent-foreground',
            )}
          >
            <ThumbsUp />
            Helpful
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-pressed={saved?.rating === 'unhelpful'}
            aria-expanded={open}
            aria-controls={`feedback-form-${messageId}`}
            disabled={pending}
            onClick={() => setOpen((v) => !v)}
            className={cn(
              saved?.rating === 'unhelpful' &&
                'border-destructive/50 bg-danger-bg text-destructive',
            )}
          >
            <ThumbsDown />
            Not helpful
          </Button>
        </div>
        {saved ? (
          <span
            role="status"
            className="inline-flex items-center gap-1 text-xs font-medium text-success"
          >
            <Check className="size-3.5" aria-hidden="true" />
            Feedback saved ({saved.rating === 'helpful' ? 'Helpful' : 'Not helpful'}
            {reasonLabel ? `: ${reasonLabel}` : ''})
          </span>
        ) : null}
      </div>
      {open ? (
        <form
          id={`feedback-form-${messageId}`}
          onSubmit={(e) => {
            e.preventDefault();
            sendDown();
          }}
          className="grid gap-3 rounded-md border bg-muted/40 p-3"
        >
          <div className="grid gap-1.5">
            <Label htmlFor={`reason-${messageId}`}>Reason (optional)</Label>
            <Select value={reason} onValueChange={(v) => setReason(v as FeedbackReason)}>
              <SelectTrigger id={`reason-${messageId}`} className="w-full sm:w-60">
                <SelectValue placeholder="Choose a reason" />
              </SelectTrigger>
              <SelectContent>
                {FEEDBACK_REASONS.map((r) => (
                  <SelectItem key={r.value} value={r.value}>
                    {r.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`comment-${messageId}`}>Comment (optional)</Label>
            <Textarea
              id={`comment-${messageId}`}
              rows={3}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              aria-describedby={`comment-count-${messageId}`}
              aria-invalid={commentOver}
              className="min-h-[64px]"
            />
            <p
              id={`comment-count-${messageId}`}
              className={cn(
                'text-xs text-muted-foreground',
                commentOver && 'font-semibold text-destructive',
              )}
            >
              No patient information. {comment.length} / {MAX_COMMENT}
            </p>
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" size="sm" disabled={commentOver} loading={pending}>
              Submit
            </Button>
          </div>
        </form>
      ) : null}
    </div>
  );
}
