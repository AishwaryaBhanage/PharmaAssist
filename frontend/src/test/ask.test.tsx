import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { state } from '@/mocks/handlers';
import { renderApp, seedSession } from './utils';

describe('ask flow', () => {
  it('submits a question with Enter, shows the answer card and saves feedback', async () => {
    const user = userEvent.setup();
    seedSession('u_dana');
    renderApp('/');
    const box = await screen.findByLabelText('Question');

    // the counter tracks the draft and the button is gated on readiness + length
    await user.type(box, 'Is Ozempic preferred on the NY Medicaid PDL?');
    expect(screen.getByText('44 / 2000')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Ask' })).toBeEnabled());
    await user.keyboard('{Enter}');

    const answer = await screen.findByRole('article', { name: 'Answer' });
    expect(within(answer).getByText('Preferred on the NYRx PDL.')).toBeInTheDocument();
    // a GFM table from the markdown answer
    expect(within(answer).getByRole('table')).toBeInTheDocument();
    // the citation links to the document
    expect(within(answer).getByText('GLP-1 Agonists sheet, row 12')).toBeInTheDocument();
    // the draft is cleared and the conversation appears in the sidebar
    expect(screen.getByLabelText('Question')).toHaveValue('');
    expect(
      await screen.findAllByText('Is Ozempic preferred on the NY Medicaid PDL?'),
    ).not.toHaveLength(0);

    await user.click(within(answer).getByRole('button', { name: 'Helpful' }));
    expect(await within(answer).findByRole('status')).toHaveTextContent('Feedback saved (Helpful)');
    const saved = state.conversations
      .flatMap((c) => c.messages)
      .find((m) => m.feedback?.rating === 'helpful' && m.question.startsWith('Is Ozempic'));
    expect(saved).toBeTruthy();
  });

  it('sends a reason and comment with an unhelpful rating', async () => {
    const user = userEvent.setup();
    seedSession('u_dana');
    renderApp('/c/c_1');
    const answers = await screen.findAllByRole('article', { name: 'Answer' });
    const second = answers[1]!;

    await user.click(within(second).getByRole('button', { name: 'Not helpful' }));
    await user.type(
      within(second).getByLabelText('Comment (optional)'),
      'Missing the quantity limit.',
    );
    await user.click(within(second).getByRole('button', { name: 'Submit' }));

    expect(await within(second).findByRole('status')).toHaveTextContent(
      'Feedback saved (Not helpful)',
    );
    const m2 = state.conversations[0]!.messages.find((m) => m.message_id === 'm_2')!;
    expect(m2.feedback).toMatchObject({
      rating: 'unhelpful',
      comment: 'Missing the quantity limit.',
    });
  });

  it('shows a toast with the request id when the API answers 5xx', async () => {
    const user = userEvent.setup();
    seedSession('u_dana');
    renderApp('/');
    const box = await screen.findByLabelText('Question');
    await user.type(box, 'please fail this one');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Ask' })).toBeEnabled());
    await user.keyboard('{Enter}');

    expect(
      await screen.findByText('The assistant could not answer right now.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Copy request id req_demo/ })).toBeInTheDocument();
  });

  it('disables asking while the API is not ready and shows the banner', async () => {
    state.ready = false;
    seedSession('u_dana');
    renderApp('/');
    expect(await screen.findByText(/The assistant is preparing/)).toBeInTheDocument();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Question'), 'A valid question');
    expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled();
  });
});
