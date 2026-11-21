import type { ReactNode } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

export function StatTile({
  label,
  value,
  hint,
  tone = 'default',
  loading,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: 'default' | 'amber' | 'danger' | 'success';
  loading?: boolean;
}) {
  return (
    <div className="rounded-lg border bg-card p-3 shadow-xs">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      {loading ? (
        <Skeleton className="mt-2 h-7 w-20" />
      ) : (
        <p
          className={cn(
            'mt-1 font-heading text-2xl font-semibold tabular-nums tracking-tight',
            tone === 'amber' && 'text-amber',
            tone === 'danger' && 'text-destructive',
            tone === 'success' && 'text-success',
          )}
        >
          {value}
        </p>
      )}
      {hint ? <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}
