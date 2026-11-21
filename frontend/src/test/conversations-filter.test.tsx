import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '@/mocks/server';
import { paramsFromSearch } from '@/pages/admin/ConversationsPage';
import { renderApp, seedSession } from './utils';

describe('admin conversations filters', () => {
  it('maps URL search params to API query params', () => {
    const p = paramsFromSearch(
      new URLSearchParams(
        'rating=helpful&status=no_answer&cached=true&user_id=u_dana&q=trulicity&since=2026-10-01&until=2026-10-18&offset=25',
      ),
    );
    expect(p).toEqual({
      offset: 25,
      limit: 25,
      rating: 'helpful',
      status: 'no_answer',
      cached: true,
      user_id: 'u_dana',
      q: 'trulicity',
      since: '2026-10-01',
      until: '2026-10-18',
    });
    expect(paramsFromSearch(new URLSearchParams('rating=bogus&cached=maybe'))).toEqual({
      offset: 0,
      limit: 25,
    });
  });

  it('sends the filters as query params and the text search updates the URL on Enter', async () => {
    const seen: URL[] = [];
    const onRequest = ({ request }: { request: Request }) => {
      const u = new URL(request.url);
      if (u.pathname === '/api/v1/admin/conversations') seen.push(u);
    };
    server.events.on('request:start', onRequest);
    onTestFinished(() => server.events.removeListener('request:start', onRequest));
    seedSession('u_admin');
    renderApp('/admin/conversations?rating=unhelpful&cached=false');

    await screen.findByRole('heading', { name: 'Conversations' });
    await waitFor(() => expect(seen.length).toBeGreaterThan(0));
    const first = seen[0]!.searchParams;
    expect(first.get('rating')).toBe('unhelpful');
    expect(first.get('cached')).toBe('false');
    expect(first.get('limit')).toBe('25');
    expect(first.get('offset')).toBe('0');

    // only the unhelpful, non-cached message is listed
    expect(await screen.findByText(/tapering a veteran stable on 90 MME/)).toBeInTheDocument();
    expect(screen.queryByText('Does Trulicity need prior auth on NY Medicaid?')).toBeNull();

    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Text'), 'naloxone{Enter}');
    await waitFor(() => expect(seen.at(-1)!.searchParams.get('q')).toBe('naloxone'));
    // rating filter is kept, offset reset
    expect(seen.at(-1)!.searchParams.get('rating')).toBe('unhelpful');
    expect(seen.at(-1)!.searchParams.get('offset')).toBe('0');
    expect(await screen.findByText('No messages match')).toBeInTheDocument();
  });
});
