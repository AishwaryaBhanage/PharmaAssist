import { screen } from '@testing-library/react';
import { renderApp, seedSession } from './utils';

describe('admin role gate', () => {
  it('shows a 403 page to staff', async () => {
    seedSession('u_dana');
    renderApp('/admin');
    expect(
      await screen.findByRole('heading', { name: /403: admin access required/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Admin' })).toBeNull();
  });

  it('renders the overview for an admin with stat tiles and the cache card', async () => {
    seedSession('u_admin');
    renderApp('/admin');
    expect(await screen.findByRole('heading', { name: 'Overview' })).toBeInTheDocument();
    expect(await screen.findByText('Active documents')).toBeInTheDocument();
    expect(await screen.findByText('Semantic cache')).toBeInTheDocument();
    expect(
      await screen.findByRole('img', { name: 'Questions and ratings per day' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Admin' })).toBeInTheDocument();
  });
});
