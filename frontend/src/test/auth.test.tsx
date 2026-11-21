import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ApiError, registerAuthHooks, request } from '@/api/client';
import { getAccessToken, setAccessToken } from '@/api/token';
import { state } from '@/mocks/handlers';
import type { UserOut } from '@/api/types';
import { renderApp, seedSession } from './utils';

describe('auth flow', () => {
  it('signs in with valid credentials and lands on Ask', async () => {
    const user = userEvent.setup();
    renderApp('/login');
    await screen.findByRole('heading', { name: 'Sign in' });

    await user.type(screen.getByLabelText('Email'), 'dana@pharmassist.local');
    await user.type(screen.getByLabelText('Password'), 'staff-password-1');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    await screen.findByText('Ask a policy or formulary question');
    expect(getAccessToken()).toMatch(/^tok_u_dana_/);
    expect(localStorage.getItem('access_token')).toBeNull();
    // the user's conversations load in the sidebar
    await screen.findByText('Is Trulicity preferred under NY Medicaid?');
  });

  it('shows the invalid_credentials error inline', async () => {
    const user = userEvent.setup();
    renderApp('/login');
    await screen.findByRole('heading', { name: 'Sign in' });
    await user.type(screen.getByLabelText('Email'), 'dana@pharmassist.local');
    await user.type(screen.getByLabelText('Password'), 'wrong-password-99');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Email or password is incorrect.');
  });

  it('restores the session from the refresh cookie and redirects an anonymous user to /login', async () => {
    renderApp('/');
    await screen.findByRole('heading', { name: 'Sign in' });
  });

  it('refreshes once on 401 token_expired and retries the request', async () => {
    seedSession('u_dana');
    setAccessToken('tok_stale_token');
    const lost = vi.fn();
    const refreshed = vi.fn();
    registerAuthHooks({ onAuthLost: lost, onTokenRefreshed: refreshed });

    const me = await request<UserOut>('/auth/me');

    expect(me.email).toBe('dana@pharmassist.local');
    expect(refreshed).toHaveBeenCalledTimes(1);
    expect(lost).not.toHaveBeenCalled();
    expect(getAccessToken()).not.toBe('tok_stale_token');
  });

  it('reports a lost session when the refresh fails', async () => {
    state.refreshUser = null;
    setAccessToken('tok_stale_token');
    const lost = vi.fn();
    registerAuthHooks({ onAuthLost: lost, onTokenRefreshed: vi.fn() });

    await expect(request('/auth/me')).rejects.toBeInstanceOf(ApiError);
    expect(lost).toHaveBeenCalledWith('expired');
    expect(getAccessToken()).toBeNull();
  });

  it('signs out from the user menu and returns to /login', async () => {
    const user = userEvent.setup();
    seedSession('u_dana');
    renderApp('/');
    await screen.findByText('Ask a policy or formulary question');

    await user.click(screen.getByRole('button', { name: 'User menu' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Sign out' }));

    await screen.findByRole('heading', { name: 'Sign in' });
    await waitFor(() => expect(getAccessToken()).toBeNull());
    expect(state.refreshUser).toBeNull();
  });
});
