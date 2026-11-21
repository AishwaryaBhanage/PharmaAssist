import { useState } from 'react';
import { Eraser } from 'lucide-react';
import { useAdminStats, useCacheStats, useClearCache } from '@/api/queries';
import { StatTile } from '@/components/admin/StatTile';
import { DailyChart } from '@/components/admin/DailyChart';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { useToast } from '@/components/ui/toast';
import { useErrorToast } from '@/lib/errors';
import { formatInt, formatPercent, formatSeconds, formatUsd, relativeTime } from '@/lib/format';
import { useDocumentTitle } from '@/lib/useDocumentTitle';
import { PageHeader } from './AdminLayout';

export function OverviewPage() {
  useDocumentTitle('Admin · Overview');
  const stats = useAdminStats(30);
  const cache = useCacheStats();
  const clear = useClearCache();
  const { toast } = useToast();
  const toastError = useErrorToast();
  const [confirm, setConfirm] = useState(false);

  const s = stats.data;
  const loading = stats.isPending;
  const rated = (s?.helpful ?? 0) + (s?.unhelpful ?? 0);
  const spendPct = s && s.spend_cap_usd > 0 ? s.spend_today_usd / s.spend_cap_usd : 0;

  return (
    <>
      <PageHeader
        title="Overview"
        description="Last 30 days of questions, ratings, latency and spend."
      />
      {stats.isError ? (
        <p role="alert" className="mb-4 rounded-md bg-danger-bg px-3 py-2 text-sm text-destructive">
          Could not load statistics.
        </p>
      ) : null}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <StatTile label="Questions" value={s ? formatInt(s.questions) : '–'} loading={loading} />
        <StatTile
          label="Answered"
          value={s ? formatPercent(s.answered, s.questions) : '–'}
          hint={s ? `${formatInt(s.answered)} answered` : undefined}
          loading={loading}
        />
        <StatTile
          label="No answer"
          value={s ? formatPercent(s.no_answer, s.questions) : '–'}
          hint={s ? `${formatInt(s.no_answer)} not found` : undefined}
          loading={loading}
        />
        <StatTile
          label="Cached (30 days)"
          value={s ? formatPercent(s.cached, s.questions) : '–'}
          hint={
            s
              ? `${formatInt(s.cached)} answers served from cache; history, not the live cache`
              : undefined
          }
          tone="amber"
          loading={loading}
        />
        <StatTile
          label="Fallback model"
          value={s ? formatInt(s.fallback) : '–'}
          hint="answers from the fallback provider"
          loading={loading}
        />
        <StatTile
          label="Helpful vs unhelpful"
          value={s ? `${formatInt(s.helpful)} / ${formatInt(s.unhelpful)}` : '–'}
          hint={
            s
              ? `${formatPercent(s.helpful, rated)} helpful of ${formatInt(rated)} rated`
              : undefined
          }
          loading={loading}
        />
        <StatTile
          label="Latency p50 / p95"
          value={s ? `${formatSeconds(s.latency_p50_s)} / ${formatSeconds(s.latency_p95_s)}` : '–'}
          loading={loading}
        />
        <StatTile
          label="Spend today"
          value={s ? `${formatUsd(s.spend_today_usd)} / ${formatUsd(s.spend_cap_usd, 0)}` : '–'}
          hint={
            s
              ? `${Math.round(spendPct * 100)}% of the daily cap · ${formatUsd(s.spend_usd)} in 30 days`
              : undefined
          }
          tone={spendPct >= 0.9 ? 'danger' : spendPct >= 0.7 ? 'amber' : 'default'}
          loading={loading}
        />
        <StatTile
          label="Active users"
          value={s ? formatInt(s.active_users) : '–'}
          hint={s ? `of ${formatInt(s.users_total)} accounts` : undefined}
          loading={loading}
        />
        <StatTile
          label="Active documents"
          value={s ? formatInt(s.documents_active) : '–'}
          loading={loading}
        />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_320px]">
        <Card>
          <CardHeader>
            <CardTitle>Questions and ratings per day</CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-48 w-full" />
            ) : (
              <DailyChart days={s?.per_day ?? []} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Semantic cache</CardTitle>
            <CardDescription>
              Answers reused when a question matches a stored one above the similarity threshold.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            {cache.isPending ? (
              <Skeleton className="h-24 w-full" />
            ) : cache.data ? (
              <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
                <Row k="Entries" v={formatInt(cache.data.entries)} />
                <Row
                  k={
                    cache.data.cleared_at
                      ? `Hit rate since clear (${relativeTime(cache.data.cleared_at)})`
                      : 'Hit rate'
                  }
                  v={`${Math.round(cache.data.hit_rate * 100)}%`}
                />
                <Row k="Hits" v={formatInt(cache.data.hits)} />
                <Row k="Misses" v={formatInt(cache.data.misses)} />
                <Row
                  k="Threshold"
                  v={cache.data.threshold != null ? cache.data.threshold.toFixed(2) : '–'}
                />
                <Row
                  k="Generation"
                  v={cache.data.generation != null ? String(cache.data.generation) : '–'}
                />
                <Row k="Backend" v={cache.data.backend} />
              </dl>
            ) : (
              <p className="text-sm text-muted-foreground">Cache statistics unavailable.</p>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => setConfirm(true)}
              disabled={clear.isPending}
            >
              <Eraser />
              Clear cache
            </Button>
          </CardContent>
        </Card>
      </div>

      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="Clear the semantic cache?"
        description="Every stored answer is dropped. The next question on each topic runs the full agent again, which costs more and takes longer."
        confirmLabel="Clear cache"
        destructive
        pending={clear.isPending}
        onConfirm={() =>
          clear.mutate(undefined, {
            onSuccess: (out) => {
              setConfirm(false);
              toast({
                kind: 'success',
                title: 'Cache cleared',
                description: `${formatInt(out?.removed ?? 0)} stored answers dropped; the hit rate counts from now.`,
              });
            },
            onError: (e) => toastError(e, 'Could not clear the cache'),
          })
        }
      />
    </>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="text-right font-medium tabular-nums">{v}</dd>
    </>
  );
}
