import { useMemo } from 'react';
import { Activity } from 'lucide-react';
import { isLiveJob, useAdminJobs } from '@/api/queries';
import type { JobOut } from '@/api/types';
import { Skeleton } from '@/components/ui/skeleton';
import { JOB_STAGES, STAGE_LABELS } from '@/lib/constants';
import { relativeTime } from '@/lib/format';
import { cn } from '@/lib/utils';
import { StatusBadge } from './StatusBadge';

function jobTime(j: JobOut): string {
  return j.finished_at ?? j.started_at ?? j.queued_at ?? '';
}

/**
 * The band of recent indexing jobs: a horizontal strip of compact cards, most recent first,
 * polled every 5 s while any job is live. Sits beside the upload control on the documents page.
 */
export function JobsPanel({
  documentTitles,
  className,
}: {
  documentTitles: Record<string, string>;
  className?: string;
}) {
  const jobs = useAdminJobs({ limit: 10 });
  const items = useMemo(
    () => [...(jobs.data?.items ?? [])].sort((a, b) => jobTime(b).localeCompare(jobTime(a))),
    [jobs.data],
  );
  const live = items.some((j) => isLiveJob(j.status, j.stage));

  return (
    <section
      className={cn('flex min-w-0 flex-col rounded-lg border bg-card shadow-xs', className)}
      aria-labelledby="jobs-heading"
    >
      <div className="flex items-center gap-2 border-b px-4 py-2.5">
        <h2 id="jobs-heading" className="text-sm font-semibold">
          Indexing jobs
        </h2>
        {live ? (
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
            <span
              aria-hidden="true"
              className="size-1.5 animate-pulse rounded-full bg-amber"
              data-testid="jobs-live-dot"
            />
            refreshing every 5 s
          </span>
        ) : null}
        <span className="ml-auto hidden text-xs text-muted-foreground sm:inline">
          Uploads and re-indexes move through parse, chunk, embed and verify.
        </span>
      </div>
      <div className="min-h-0 flex-1 px-3 py-3">
        {jobs.isPending ? (
          <div className="flex gap-3" aria-busy="true">
            <Skeleton className="h-24 w-64 shrink-0" />
            <Skeleton className="h-24 w-64 shrink-0" />
            <Skeleton className="hidden h-24 w-64 shrink-0 lg:block" />
          </div>
        ) : jobs.isError ? (
          <p role="alert" className="text-sm text-destructive">
            Could not load jobs.
          </p>
        ) : !items.length ? (
          <p className="flex h-24 items-center justify-center gap-2 rounded-md border border-dashed text-sm text-muted-foreground">
            <Activity className="size-4" aria-hidden="true" />
            No indexing jobs yet. Upload a document to start one.
          </p>
        ) : (
          <ul className="flex snap-x gap-3 overflow-x-auto pb-1" aria-label="Recent jobs">
            {items.map((j) => (
              <JobCard key={j.id} job={j} title={documentTitles[j.document_id] ?? j.document_id} />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function JobCard({ job, title }: { job: JobOut; title: string }) {
  const failed = job.status === 'failed';
  const stage = failed ? (job.stage ?? 'failed') : (job.stage ?? job.status);
  const idx = JOB_STAGES.indexOf(stage as (typeof JOB_STAGES)[number]);
  const done = job.status === 'active' || job.status === 'done' || stage === 'active';
  const reached = done ? JOB_STAGES.length : Math.max(idx, 0) + (idx >= 0 ? 1 : 0);
  const stepLabel = done
    ? 'Complete'
    : failed
      ? `Failed at ${STAGE_LABELS[stage] ?? stage}`
      : `Step ${Math.max(idx, 0) + 1} of ${JOB_STAGES.length} · ${STAGE_LABELS[stage] ?? stage}`;
  const when = job.finished_at
    ? `finished ${relativeTime(job.finished_at)}`
    : job.started_at
      ? `started ${relativeTime(job.started_at)}`
      : job.queued_at
        ? `queued ${relativeTime(job.queued_at)}`
        : '';

  return (
    <li
      className="flex w-64 shrink-0 snap-start flex-col gap-2 rounded-md border bg-background/60 p-3 text-sm sm:w-72"
      data-testid="job-card"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="line-clamp-2 min-w-0 font-medium leading-snug" title={title}>
          {title}
        </span>
        <StatusBadge status={job.status} stage={job.stage} />
      </div>
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="truncate">{stepLabel}</span>
        <span className="shrink-0 whitespace-nowrap">
          {job.attempt > 1 ? `attempt ${job.attempt} · ` : ''}
          {when}
        </span>
      </div>
      <ol className="flex gap-1" aria-label="Stages">
        {JOB_STAGES.map((s, i) => {
          const current = !done && i === idx;
          return (
            <li
              key={s}
              className={cn(
                'h-1.5 flex-1 rounded-full bg-muted',
                i < reached && 'bg-primary/70',
                current && !failed && 'animate-pulse bg-primary',
                current && failed && 'bg-destructive',
              )}
              title={STAGE_LABELS[s]}
              aria-current={current ? 'step' : undefined}
            >
              <span className="sr-only">{STAGE_LABELS[s]}</span>
            </li>
          );
        })}
      </ol>
      {failed && job.error ? (
        <p
          className="line-clamp-2 rounded-md bg-danger-bg px-2 py-1 text-xs leading-snug text-destructive"
          role="alert"
          title={job.error}
        >
          {job.error}
        </p>
      ) : null}
    </li>
  );
}
