import { useState } from 'react';
import { Link } from 'react-router';
import { MessageSquare, Plus, Trash2 } from 'lucide-react';
import type { ConversationSummaryOut } from '@/api/types';
import { useConversations, useDeleteConversation } from '@/api/queries';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { useErrorToast } from '@/lib/errors';
import { relativeTime } from '@/lib/format';
import { cn } from '@/lib/utils';

export function ConversationSidebar({
  selectedId,
  onSelect,
  onNew,
  onDeleted,
}: {
  selectedId: string | null;
  onSelect?: () => void;
  onNew: () => void;
  onDeleted: (id: string) => void;
}) {
  const { data, isPending, isError } = useConversations();
  const del = useDeleteConversation();
  const toastError = useErrorToast();
  const [confirm, setConfirm] = useState<ConversationSummaryOut | null>(null);

  function confirmDelete() {
    if (!confirm) return;
    const id = confirm.id;
    del.mutate(id, {
      onSuccess: () => {
        setConfirm(null);
        onDeleted(id);
      },
      onError: (e) => toastError(e, 'Could not delete the conversation'),
    });
  }

  const count = data?.total ?? data?.items.length;

  return (
    <nav className="flex min-h-0 flex-1 flex-col" aria-label="Conversations">
      <div className="shrink-0 p-4 pb-2">
        <Button className="h-10 w-full justify-center shadow-xs" onClick={onNew}>
          <Plus className="size-4" strokeWidth={2.5} />
          New question
        </Button>
      </div>
      <div className="flex shrink-0 items-center justify-between px-4 pb-1 pt-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Conversations
        </h2>
        {typeof count === 'number' && count > 0 ? (
          <span
            className="rounded-full bg-muted px-1.5 text-[11px] font-medium tabular-nums text-muted-foreground"
            aria-label={`${count} conversations`}
          >
            {count}
          </span>
        ) : null}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 pb-3">
        {isPending ? (
          <ul className="grid gap-1" aria-busy="true">
            {Array.from({ length: 5 }).map((_, i) => (
              <li key={i} className="px-3 py-2">
                <Skeleton className="h-3.5 w-11/12" />
                <Skeleton className="mt-2 h-3 w-1/3" />
              </li>
            ))}
          </ul>
        ) : isError ? (
          <p className="px-3 py-3 text-sm text-muted-foreground">Could not load conversations.</p>
        ) : !data?.items.length ? (
          <div className="mx-1 mt-1 flex flex-col items-center gap-2 rounded-lg border border-dashed px-3 py-6 text-center">
            <MessageSquare className="size-4 text-muted-foreground" aria-hidden="true" />
            <p className="text-sm text-muted-foreground">Your questions will appear here.</p>
          </div>
        ) : (
          <ul className="grid gap-0.5">
            {data.items.map((c) => {
              const active = c.id === selectedId;
              return (
                <li key={c.id} className="group relative min-w-0">
                  <Link
                    to={`/c/${encodeURIComponent(c.id)}`}
                    onClick={onSelect}
                    aria-current={active ? 'page' : undefined}
                    className={cn(
                      'block rounded-md border-l-2 border-transparent py-2 pl-3 pr-9 text-sm transition-colors hover:bg-secondary/70 focus-visible:outline-2 focus-visible:outline-ring',
                      active && 'border-primary bg-accent/50 hover:bg-accent/50',
                    )}
                  >
                    <span
                      className={cn(
                        'block truncate font-medium text-foreground/90',
                        active && 'text-foreground',
                      )}
                    >
                      {c.title || 'Untitled'}
                    </span>
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      {relativeTime(c.updated_at)}
                      {c.message_count > 1 ? ` · ${c.message_count} questions` : ''}
                    </span>
                  </Link>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Delete conversation: ${c.title}`}
                    className="absolute right-1 top-1/2 -translate-y-1/2 text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100 focus-visible:opacity-100"
                    onClick={() => setConfirm(c)}
                  >
                    <Trash2 />
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      <ConfirmDialog
        open={!!confirm}
        onOpenChange={(o) => !o && setConfirm(null)}
        title="Delete this conversation?"
        description={
          <>
            <span className="font-medium text-foreground">{confirm?.title}</span> and its answers
            will be removed from your history. This cannot be undone.
          </>
        }
        confirmLabel="Delete"
        destructive
        pending={del.isPending}
        onConfirm={confirmDelete}
      />
    </nav>
  );
}
