import { useState } from 'react';
import { useSearchParams } from 'react-router';
import { Search } from 'lucide-react';
import type { Role, UserOut, UserPatchIn } from '@/api/types';
import { useAdminUsers, usePatchUser } from '@/api/queries';
import { useAuth } from '@/auth/AuthProvider';
import { Badge } from '@/components/ui/badge';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { EmptyState } from '@/components/ui/empty-state';
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
import { Switch } from '@/components/ui/switch';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useToast } from '@/components/ui/toast';
import { useErrorToast } from '@/lib/errors';
import { formatDateTime, relativeTime } from '@/lib/format';
import { useDocumentTitle } from '@/lib/useDocumentTitle';
import { PageHeader } from './AdminLayout';

const LIMIT = 25;

interface PendingChange {
  user: UserOut;
  patch: UserPatchIn;
  title: string;
  description: string;
}

export function UsersPage() {
  useDocumentTitle('Admin · Users');
  const { user: me, updateUser } = useAuth();
  const [sp, setSp] = useSearchParams();
  const q = sp.get('q') ?? '';
  const offset = Number(sp.get('offset') ?? 0) || 0;
  const [draftQ, setDraftQ] = useState(q);
  const users = useAdminUsers({ q: q || undefined, offset, limit: LIMIT });
  const patch = usePatchUser();
  const { toast } = useToast();
  const toastError = useErrorToast();
  const [pending, setPending] = useState<PendingChange | null>(null);

  function setParam(k: string, v: string | undefined, resetOffset = true) {
    const next = new URLSearchParams(sp);
    if (v) next.set(k, v);
    else next.delete(k);
    if (resetOffset) next.delete('offset');
    setSp(next, { replace: true });
  }

  function apply() {
    if (!pending) return;
    patch.mutate(
      { id: pending.user.id, body: pending.patch },
      {
        onSuccess: (updated) => {
          setPending(null);
          if (updated.id === me?.id) updateUser(updated);
          toast({ kind: 'success', title: 'User updated', description: updated.email });
        },
        onError: (e) => toastError(e, 'Could not update the user'),
      },
    );
  }

  return (
    <>
      <PageHeader title="Users" description="Roles and access. New sign-ups start as staff." />

      <form
        className="mb-3 flex shrink-0 items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setParam('q', draftQ.trim() || undefined);
        }}
        role="search"
      >
        <div className="grid flex-1 gap-1 sm:max-w-sm">
          <Label htmlFor="user-q">Search</Label>
          <div className="relative">
            <Search
              className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              id="user-q"
              value={draftQ}
              onChange={(e) => setDraftQ(e.target.value)}
              onBlur={() => draftQ.trim() !== q && setParam('q', draftQ.trim() || undefined)}
              placeholder="Email or name"
              className="pl-8"
            />
          </div>
        </div>
      </form>

      <div className="flex min-h-0 flex-col overflow-hidden rounded-lg border bg-card">
        {users.isPending ? (
          <div className="grid gap-2 p-3" aria-busy="true">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : users.isError ? (
          <p role="alert" className="p-4 text-sm text-destructive">
            Could not load users.
          </p>
        ) : !users.data.items.length ? (
          <EmptyState title="No users match" className="m-3" />
        ) : (
          <Table containerClassName="min-h-0 flex-1">
            <TableHeader className="sticky top-0 z-10">
              <TableRow>
                <TableHead>User</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Active</TableHead>
                <TableHead>Last sign-in</TableHead>
                <TableHead>Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.data.items.map((u) => {
                const self = u.id === me?.id;
                return (
                  <TableRow key={u.id}>
                    <TableCell>
                      <div className="flex items-center gap-2 font-medium">
                        {u.display_name || <span className="text-muted-foreground">(no name)</span>}
                        {self ? <Badge variant="muted">you</Badge> : null}
                      </div>
                      <div className="text-xs text-muted-foreground">{u.email}</div>
                    </TableCell>
                    <TableCell>
                      <Select
                        value={u.role}
                        disabled={self || patch.isPending}
                        onValueChange={(v) => {
                          const role = v as Role;
                          if (role === u.role) return;
                          setPending({
                            user: u,
                            patch: { role },
                            title: `Make ${u.email} ${role === 'admin' ? 'an admin' : 'staff'}?`,
                            description:
                              role === 'admin'
                                ? 'Admins see every conversation, rating and comment, upload documents and manage users.'
                                : 'They lose access to the admin area immediately.',
                          });
                        }}
                      >
                        <SelectTrigger className="h-8 w-28" aria-label={`Role for ${u.email}`}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="staff">staff</SelectItem>
                          <SelectItem value="admin">admin</SelectItem>
                        </SelectContent>
                      </Select>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Switch
                          checked={u.is_active}
                          disabled={self || patch.isPending}
                          aria-label={`${u.is_active ? 'Deactivate' : 'Activate'} ${u.email}`}
                          onCheckedChange={(checked) =>
                            setPending({
                              user: u,
                              patch: { is_active: checked },
                              title: checked ? `Reactivate ${u.email}?` : `Deactivate ${u.email}?`,
                              description: checked
                                ? 'They can sign in again.'
                                : 'They are signed out everywhere and cannot sign in until reactivated. Their conversations are kept.',
                            })
                          }
                        />
                        <span className="text-xs text-muted-foreground">
                          {u.is_active ? 'active' : 'inactive'}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {u.last_login_at ? relativeTime(u.last_login_at) : 'never'}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {formatDateTime(u.created_at)}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
        {users.data ? (
          <div className="shrink-0 border-t p-3">
            <Pagination
              offset={offset}
              limit={LIMIT}
              total={users.data.total}
              onChange={(o) => setParam('offset', o ? String(o) : undefined, false)}
            />
          </div>
        ) : null}
      </div>

      <ConfirmDialog
        open={!!pending}
        onOpenChange={(o) => !o && setPending(null)}
        title={pending?.title ?? ''}
        description={pending?.description}
        confirmLabel="Confirm"
        destructive={pending?.patch.is_active === false}
        pending={patch.isPending}
        onConfirm={apply}
      />
    </>
  );
}
