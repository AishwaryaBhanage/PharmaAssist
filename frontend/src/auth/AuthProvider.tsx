import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { auth as authApi } from '@/api/endpoints';
import { refreshSession, registerAuthHooks } from '@/api/client';
import { setAccessToken } from '@/api/token';
import type { LoginIn, SignupIn, TokenOut, UserOut } from '@/api/types';

export type AuthStatus = 'restoring' | 'authenticated' | 'anonymous';

export interface AuthState {
  status: AuthStatus;
  user: UserOut | null;
  /** set when the session ended because a refresh failed, so /login can explain why */
  lostReason: 'expired' | null;
  login: (body: LoginIn) => Promise<UserOut>;
  signup: (body: SignupIn) => Promise<UserOut>;
  logout: () => Promise<void>;
  updateUser: (u: UserOut) => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>('restoring');
  const [user, setUser] = useState<UserOut | null>(null);
  const [lostReason, setLostReason] = useState<'expired' | null>(null);
  const expiryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scheduleRefresh = useCallback((expiresIn: number) => {
    if (expiryTimer.current) clearTimeout(expiryTimer.current);
    // refresh a minute before the access token expires (never sooner than 10 s)
    const ms = Math.max(10_000, (expiresIn - 60) * 1000);
    expiryTimer.current = setTimeout(() => void refreshSession(), ms);
  }, []);

  const accept = useCallback(
    (token: TokenOut) => {
      setAccessToken(token.access_token);
      setUser(token.user);
      setStatus('authenticated');
      setLostReason(null);
      scheduleRefresh(token.expires_in);
    },
    [scheduleRefresh],
  );

  const clear = useCallback(
    (reason: 'expired' | 'logged_out') => {
      setAccessToken(null);
      setUser(null);
      setStatus('anonymous');
      setLostReason(reason === 'expired' ? 'expired' : null);
      if (expiryTimer.current) clearTimeout(expiryTimer.current);
      qc.clear();
    },
    [qc],
  );

  useEffect(() => {
    registerAuthHooks({
      onAuthLost: (reason) => clear(reason),
      onTokenRefreshed: (token) => accept(token),
    });
  }, [accept, clear]);

  // Restore the session silently on load via the refresh cookie.
  useEffect(() => {
    let cancelled = false;
    void refreshSession().then((token) => {
      if (cancelled) return;
      if (token) accept(token);
      else setStatus('anonymous');
    });
    return () => {
      cancelled = true;
      if (expiryTimer.current) clearTimeout(expiryTimer.current);
    };
  }, [accept]);

  const login = useCallback(
    async (body: LoginIn) => {
      const token = await authApi.login(body);
      accept(token);
      return token.user;
    },
    [accept],
  );

  const signup = useCallback(
    async (body: SignupIn) => {
      const token = await authApi.signup(body);
      accept(token);
      return token.user;
    },
    [accept],
  );

  const logout = useCallback(async () => {
    await authApi.logout();
    clear('logged_out');
  }, [clear]);

  const value = useMemo<AuthState>(
    () => ({ status, user, lostReason, login, signup, logout, updateUser: setUser }),
    [status, user, lostReason, login, signup, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}
