import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';
import { Search, X } from 'lucide-react';
import type { AdminConversationsParams, AdminMessageOut } from '@/api/types';
import { useAdminConversations } from '@/api/queries';
import { MessageDrawer } from '@/components/admin/MessageDrawer';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Pagination } from '@/components/ui/pagination';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { EmptyState } from '@/components/ui/empty-state';
import { formatDateTime, formatSeconds } from '@/lib/format';
import { useDocumentTitle } from '@/lib/useDocumentTitle';
import { isNoAnswer } from '@/components/ask/AnswerCard';
import { PageHeader } from './AdminLayout';

const LIMIT = 25;
const ANY = 'any';

/** URL search params are the single source of truth for the filters, so views are linkable. */
export function paramsFromSearch(sp: URLSearchParams): AdminConversationsParams {
  const p: AdminConversationsParams = { offset: Number(sp.get('offset') ?? 0) || 0, limit: LIMIT };
  const rating = sp.get('rating');
  if (rating === 'helpful' || rating === 'unhelpful') p.rating = rating;
  const status = sp.get('status');
  if (status === 'answered' || status === 'no_answer') p.status = status;
  const cached = sp.get('cached');
  if (cached === 'true' || cached === 'false') p.cached = cached === 'true';
  for (const k of ['user_id', 'q', 'since', 'until'] as const) {
    const v = sp.get(k);
    if (v) p[k] = v;
  }
  return p;
}

export function ConversationsPage() {
  useDocumentTitle('Admin · Conversations');
  const [sp, setSp] = useSearchParams();
  const params = useMemo(() => paramsFromSearch(sp), [sp]);
  const [draftQ, setDraftQ] = useState(params.q ?? '');
  const [selected, setSelected] = useState<AdminMessageOut | null>(null);
  const query = useAdminConversations(params);

  function update(patch: Record<string, string | undefined>, resetOffset = true) {
    const next = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined || v === '' || v === ANY) next.delete(k);
      else next.set(k, v);
    }
    if (resetOffset) next.delete('offset');
    setSp(next, { replace: true });
  }

  const hasFilters = ['rating', 'status', 'cached', 'user_id', 'q', 'since', 'until'].some((k) =>
    sp.has(k),
  );

  return (
    <>
      <PageHeader
        title="Conversations"
        description="Every question asked, with ratings and comments."
      />

      <form
        className="mb-3 grid shrink-0 gap-3 rounded-lg border bg-card p-3 sm:grid-cols-2 lg:grid-cols-6"
        onSubmit={(e) => {
          e.preventDefault();
          update({ q: draftQ.trim() || undefined });
        }}
        aria-label="Filters"
      >
        <div className="grid gap-1 lg:col-span-2">
          <Label htmlFor="f-q">Text</Label>
          <div className="relative">
            <Search
              className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              id="f-q"
              value={draftQ}
              onChange={(e) => setDraftQ(e.target.value)}
              onBlur={() =>
                draftQ.trim() !== (params.q ?? '') && update({ q: draftQ.trim() || undefined })
              }
              placeholder="Search questions and answers"
              className="pl-8"
            />
          </div>
        </div>
        <FilterSelect
          id="f-rating"
          label="Rating"
          value={params.rating ?? ANY}
          onChange={(v) => update({ rating: v })}
          options={[
            [ANY, 'Any'],
            ['helpful', 'Helpful'],
            ['unhelpful', 'Unhelpful'],
          ]}
        />
        <FilterSelect
          id="f-status"
          label="Status"
          value={params.status ?? ANY}
          onChange={(v) => update({ status: v })}
          options={[
            [ANY, 'Any'],
            ['answered', 'Answered'],
            ['no_answer', 'No answer'],
          ]}
        />
        <FilterSelect
          id="f-cached"
          label="Cached"
          value={params.cached === undefined ? ANY : String(params.cached)}
          onChange={(v) => update({ cached: v })}
          options={[
            [ANY, 'Any'],
            ['true', 'Cached only'],
            ['false', 'Not cached'],
          ]}
        />
        <div className="grid gap-1">
          <Label htmlFor="f-user">User id</Label>
          <Input
            id="f-user"
            defaultValue={params.user_id ?? ''}
            onBlur={(e) => update({ user_id: e.target.value.trim() || undefined })}
            placeholder="u_…"
          />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="f-since">From</Label>
          <Input
            id="f-since"
            type="date"
            value={params.since ?? ''}
            onChange={(e) => update({ since: e.target.value || undefined })}
          />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="f-until">To</Label>
          <Input
            id="f-until"
            type="date"
            value={params.until ?? ''}
            onChange={(e) => update({ until: e.target.value || undefined })}
          />
        </div>
        <div className="flex items-end gap-2 lg:col-span-4 lg:justify-end">
          <Button type="submit" size="sm" variant="secondary">
            Apply
          </Button>
          {hasFilters ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => {
                setDraftQ('');
                setSp(new URLSearchParams(), { replace: true });
              }}
            >
              <X />
              Clear filters
            </Button>
          ) : null}
        </div>
      </form>

      <div className="flex min-h-0 flex-col overflow-hidden rounded-lg border bg-card">
        {query.isPending ? (
          <div className="grid gap-2 p-3" aria-busy="true">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        ) : query.isError ? (
          <p role="alert" className="p-4 text-sm text-destructive">
            Could not load conversations.
          </p>
        ) : !query.data.items.length ? (
          <EmptyState
            title="No messages match"
            description="Try widening the filters."
            className="m-3"
          />
        ) : (
          <Table containerClassName="min-h-0 flex-1">
            <TableHeader className="sticky top-0 z-10">
              <TableRow>
                <TableHead>When</TableHead>
                <TableHead>User</TableHead>
                <TableHead className="w-[40%]">Question</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Rating</TableHead>
                <TableHead className="text-right">Latency</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.data.items.map((m) => (
                <TableRow
                  key={m.message_id}
                  tabIndex={0}
                  role="button"
                  aria-label={`Open message: ${m.question}`}
                  className="cursor-pointer focus-visible:bg-muted focus-visible:outline-hidden"
                  onClick={() => setSelected(m)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      setSelected(m);
                    }
                  }}
                >
                  <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                    {formatDateTime(m.created_at)}
                  </TableCell>
                  <TableCell className="max-w-[12rem] truncate text-xs">{m.user_email}</TableCell>
                  <TableCell className="max-w-md truncate">{m.question}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {isNoAnswer(m) ? (
                        <Badge variant="muted">No answer</Badge>
                      ) : (
                        <Badge variant="success">Answered</Badge>
                      )}
                      {m.cached ? <Badge variant="amber">Cached</Badge> : null}
                      {m.fallback_used ? <Badge variant="outline">Fallback</Badge> : null}
                    </div>
                  </TableCell>
                  <TableCell>
                    {m.feedback ? (
                      <Badge variant={m.feedback.rating === 'helpful' ? 'success' : 'destructive'}>
                        {m.feedback.rating === 'helpful' ? 'Helpful' : 'Unhelpful'}
                      </Badge>
                    ) : (
                      <span className="text-xs text-muted-foreground">–</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-xs">
                    {formatSeconds(m.latency_seconds)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        {query.data ? (
          <div className="shrink-0 border-t p-3">
            <Pagination
              offset={params.offset ?? 0}
              limit={LIMIT}
              total={query.data.total}
              onChange={(offset) => update({ offset: String(offset) }, false)}
            />
          </div>
        ) : null}
      </div>

      <MessageDrawer
        messageId={selected?.message_id ?? null}
        initial={selected}
        onClose={() => setSelected(null)}
      />
    </>
  );
}

function FilterSelect({
  id,
  label,
  value,
  onChange,
  options,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: Array<[string, string]>;
}) {
  return (
    <div className="grid gap-1">
      <Label htmlFor={id}>{label}</Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map(([v, l]) => (
            <SelectItem key={v} value={v}>
              {l}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
