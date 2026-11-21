import { useLocation, useNavigate } from 'react-router';

/** Send the user back to where they were heading before /login (defaults to "/"). */
export function useAfterLogin(): () => void {
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from;
  const target =
    from && from.startsWith('/') && !from.startsWith('/login') && !from.startsWith('/signup')
      ? from
      : '/';
  return () => navigate(target, { replace: true });
}
