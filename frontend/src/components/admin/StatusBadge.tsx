import { Badge } from '@/components/ui/badge';
import { STAGE_LABELS } from '@/lib/constants';

const LIVE = new Set([
  'queued',
  'running',
  'parsing',
  'extracting_figures',
  'chunking',
  'embedding',
  'verifying',
]);

/** Version/job status pill with the stage name. */
export function StatusBadge({
  status,
  stage,
}: {
  status: string | null | undefined;
  stage?: string | null;
}) {
  const s = status ?? 'unknown';
  const label = STAGE_LABELS[stage && LIVE.has(s) ? stage : s] ?? s;
  const variant =
    s === 'active' || s === 'done'
      ? 'success'
      : s === 'failed'
        ? 'destructive'
        : s === 'superseded'
          ? 'muted'
          : LIVE.has(s)
            ? 'amber'
            : 'outline';
  return (
    <Badge variant={variant}>
      {LIVE.has(s) ? (
        <span aria-hidden="true" className="size-1.5 animate-pulse rounded-full bg-current" />
      ) : null}
      {label}
    </Badge>
  );
}
