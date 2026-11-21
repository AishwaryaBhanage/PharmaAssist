import type { ReactNode } from 'react';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { Providers, AppRoutes, makeQueryClient } from '@/App';
import { state } from '@/mocks/handlers';

/** Mount the full app at a route, with a fresh QueryClient and no retries. */
export function renderApp(initialPath = '/') {
  const client = makeQueryClient();
  client.setDefaultOptions({ queries: { retry: false, staleTime: 0 } });
  return render(
    <Providers client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <AppRoutes />
      </MemoryRouter>
    </Providers>,
  );
}

/** Mount an arbitrary tree inside the providers. */
export function renderWithProviders(ui: ReactNode, initialPath = '/') {
  const client = makeQueryClient();
  client.setDefaultOptions({ queries: { retry: false, staleTime: 0 } });
  return render(
    <Providers client={client}>
      <MemoryRouter initialEntries={[initialPath]}>{ui}</MemoryRouter>
    </Providers>,
  );
}

/** Pretend the refresh cookie exists for this mock user, so the app restores the session on load. */
export function seedSession(userId: 'u_admin' | 'u_dana' | 'u_marcus' | 'u_sofia'): void {
  state.refreshUser = userId;
}
