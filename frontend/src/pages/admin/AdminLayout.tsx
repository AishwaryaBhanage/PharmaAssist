import { Suspense } from 'react';
import { NavLink, Outlet } from 'react-router';
import { TopBar } from '@/components/layout/TopBar';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

const LINKS = [
  { to: '/admin', label: 'Overview', end: true },
  { to: '/admin/conversations', label: 'Conversations' },
  { to: '/admin/documents', label: 'Documents' },
  { to: '/admin/users', label: 'Users' },
];

export function AdminLayout() {
  // Same fixed shell as the Ask page: header and section tabs stay put, <main> is the only
  // scrolling region. Pages that render a table shrink it to the available height so the
  // table scrolls inside its card and the pagination stays visible.
  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <TopBar />
      <div className="shrink-0 border-b bg-card">
        <nav
          className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-3 sm:px-6"
          aria-label="Admin sections"
        >
          {LINKS.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.end}
              className={({ isActive }) =>
                cn(
                  '-mb-px whitespace-nowrap border-b-2 border-transparent px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground',
                  isActive && 'border-primary text-foreground',
                )
              }
            >
              {l.label}
            </NavLink>
          ))}
        </nav>
      </div>
      <main className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 py-4 sm:px-6">
        <div className="mx-auto flex h-full w-full max-w-6xl flex-col">
          <Suspense
            fallback={
              <div className="grid gap-3" aria-busy="true">
                <Skeleton className="h-6 w-40" />
                <Skeleton className="h-32 w-full" />
              </div>
            }
          >
            <Outlet />
          </Suspense>
        </div>
      </main>
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-3 flex shrink-0 flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-lg font-semibold">{title}</h1>
        {description ? <p className="text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}
