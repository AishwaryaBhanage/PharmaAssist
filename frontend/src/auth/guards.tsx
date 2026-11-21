import { Navigate, Outlet, useLocation } from 'react-router';
import { useAuth } from './AuthProvider';
import { FullPageSpinner } from '@/components/layout/FullPageSpinner';
import { ForbiddenPage } from '@/pages/ForbiddenPage';

/** Routes that need a signed-in user; remembers where the user was going. */
export function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();
  if (status === 'restoring') return <FullPageSpinner label="Restoring your session" />;
  if (status === 'anonymous') {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return <Outlet />;
}

/** Admin-only routes: staff see a 403 page instead of a redirect. */
export function RequireAdmin() {
  const { user } = useAuth();
  if (user?.role !== 'admin') return <ForbiddenPage />;
  return <Outlet />;
}

/** /login and /signup send an already-authenticated user back to the app. */
export function RedirectIfAuthed() {
  const { status } = useAuth();
  if (status === 'restoring') return <FullPageSpinner label="Restoring your session" />;
  if (status === 'authenticated') return <Navigate to="/" replace />;
  return <Outlet />;
}
