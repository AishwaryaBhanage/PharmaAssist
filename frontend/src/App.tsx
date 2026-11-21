import { lazy, Suspense } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Route, Routes } from 'react-router';
import { AuthProvider } from '@/auth/AuthProvider';
import { RedirectIfAuthed, RequireAdmin, RequireAuth } from '@/auth/guards';
import { ToastProvider } from '@/components/ui/toast';
import { TooltipProvider } from '@/components/ui/tooltip';
import { FullPageSpinner } from '@/components/layout/FullPageSpinner';
import { isApiError } from '@/api/client';
import { LoginPage } from '@/pages/auth/LoginPage';
import { SignupPage } from '@/pages/auth/SignupPage';
import { AskPage } from '@/pages/AskPage';
import { NotFoundPage } from '@/pages/NotFoundPage';

// The admin area is only for admins, so it loads on demand.
const AdminLayout = lazy(() =>
  import('@/pages/admin/AdminLayout').then((m) => ({ default: m.AdminLayout })),
);
const OverviewPage = lazy(() =>
  import('@/pages/admin/OverviewPage').then((m) => ({ default: m.OverviewPage })),
);
const ConversationsPage = lazy(() =>
  import('@/pages/admin/ConversationsPage').then((m) => ({ default: m.ConversationsPage })),
);
const DocumentsPage = lazy(() =>
  import('@/pages/admin/DocumentsPage').then((m) => ({ default: m.DocumentsPage })),
);
const UsersPage = lazy(() =>
  import('@/pages/admin/UsersPage').then((m) => ({ default: m.UsersPage })),
);

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: (count, error) => {
          // never retry auth/validation failures; one retry for everything else
          if (isApiError(error) && error.status > 0 && error.status < 500) return false;
          return count < 1;
        },
      },
    },
  });
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<RedirectIfAuthed />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
      </Route>
      <Route element={<RequireAuth />}>
        <Route path="/" element={<AskPage />} />
        <Route path="/c/:conversationId" element={<AskPage />} />
        <Route element={<RequireAdmin />}>
          <Route
            path="/admin"
            element={
              <Suspense fallback={<FullPageSpinner label="Loading admin" />}>
                <AdminLayout />
              </Suspense>
            }
          >
            <Route index element={<OverviewPage />} />
            <Route path="conversations" element={<ConversationsPage />} />
            <Route path="documents" element={<DocumentsPage />} />
            <Route path="users" element={<UsersPage />} />
          </Route>
        </Route>
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}

/** Everything but the router, so tests can mount with a MemoryRouter. */
export function Providers({
  children,
  client,
}: {
  children: React.ReactNode;
  client?: QueryClient;
}) {
  return (
    <QueryClientProvider client={client ?? makeQueryClient()}>
      <TooltipProvider delayDuration={200}>
        <ToastProvider>
          <AuthProvider>{children}</AuthProvider>
        </ToastProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
}

const queryClient = makeQueryClient();

export function App() {
  return (
    <Providers client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </Providers>
  );
}
