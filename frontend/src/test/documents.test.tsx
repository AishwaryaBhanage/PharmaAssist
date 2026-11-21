import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { state } from '@/mocks/handlers';
import { renderApp, seedSession } from './utils';

const NY = 'ny_medicaid_pdl_2025';
const VA = 'va_dod_cpg_opioids_2022';
const VANF = 'va_national_formulary_2024';

describe('admin documents page', () => {
  it('lays out upload and jobs on top and the documents table with a Version column below', async () => {
    seedSession('u_admin');
    renderApp('/admin/documents');
    expect(await screen.findByRole('heading', { name: 'Documents' })).toBeInTheDocument();

    // top band
    expect(screen.getByRole('heading', { name: 'Add a document' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Upload' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Indexing jobs' })).toBeInTheDocument();
    const jobs = await screen.findByRole('list', { name: 'Recent jobs' });
    expect(within(jobs).getAllByTestId('job-card')).toHaveLength(3);

    // table: the Version column shows the active version's file, short id and counts
    const table = screen.getByRole('table');
    expect(within(table).getByRole('columnheader', { name: 'Version' })).toBeInTheDocument();
    const ny = within(table).getByTestId(`doc-row-${NY}`);
    expect(within(ny).getByText('ny_pdl_2025_07.xlsx')).toBeInTheDocument();
    expect(within(ny).getByText('v_ny_4')).toBeInTheDocument();
    expect(within(ny).getByText(/1,204 chunks/)).toBeInTheDocument();
    expect(within(ny).getByText('Active')).toBeInTheDocument();

    // a document whose index was removed: latest file name, "Not indexed", re-index still offered
    const vanf = within(table).getByTestId(`doc-row-${VANF}`);
    expect(within(vanf).getByText('va_national_formulary_2024_11.xlsx')).toBeInTheDocument();
    expect(within(vanf).getByText('Not indexed')).toBeInTheDocument();
    expect(within(vanf).getByRole('button', { name: /^Re-index/ })).toBeEnabled();
    expect(within(vanf).getByRole('button', { name: /from the index$/ })).toBeDisabled();

    // a document with a running job: "Indexing…" and both actions locked
    const va = within(table).getByTestId(`doc-row-${VA}`);
    expect(within(va).getByText('Indexing…')).toBeInTheDocument();
    expect(within(va).getByRole('button', { name: /^Re-index/ })).toBeDisabled();
    expect(within(va).getByRole('button', { name: /from the index$/ })).toBeDisabled();
  });

  it('removes a document from the index after confirmation and keeps it re-indexable', async () => {
    const user = userEvent.setup();
    seedSession('u_admin');
    renderApp('/admin/documents');
    const table = await screen.findByRole('table');
    const ny = within(table).getByTestId(`doc-row-${NY}`);

    await user.click(
      within(ny).getByRole('button', {
        name: 'Remove New York State Medicaid Preferred Drug List from the index',
      }),
    );
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent(
      'Remove New York State Medicaid Preferred Drug List from the index?',
    );
    expect(dialog).toHaveTextContent(
      'Its chunks, embeddings, figures and table rows are deleted and the assistant stops citing it. The uploaded file stays, so you can re-index it later.',
    );
    await user.click(within(dialog).getByRole('button', { name: 'Remove from index' }));

    expect(
      await screen.findByText(
        'New York State Medicaid Preferred Drug List removed from the index (1,204 chunks)',
      ),
    ).toBeInTheDocument();

    const doc = state.documents.find((d) => d.id === NY)!;
    expect(doc.active_version).toBeNull();
    expect(doc.latest_version?.status).toBe('superseded');

    await waitFor(() => expect(within(ny).getByText('Not indexed')).toBeInTheDocument());
    expect(within(ny).getByRole('button', { name: /^Re-index/ })).toBeEnabled();
    expect(within(ny).getByRole('button', { name: /from the index$/ })).toBeDisabled();
  });

  it('shows the server conflict when a job starts before the removal is confirmed', async () => {
    const user = userEvent.setup();
    // the VA document's fixture job is live; finish it so the action is offered
    state.jobs = state.jobs.map((j) =>
      j.document_id === VA
        ? { ...j, status: 'active', stage: 'active', finished_at: new Date().toISOString() }
        : j,
    );
    seedSession('u_admin');
    renderApp('/admin/documents');
    const table = await screen.findByRole('table');
    const va = within(table).getByTestId(`doc-row-${VA}`);
    const remove = within(va).getByRole('button', { name: /from the index$/ });
    await waitFor(() => expect(remove).toBeEnabled());
    await user.click(remove);
    const dialog = await screen.findByRole('alertdialog');

    // a re-index is queued elsewhere in the meantime: the API answers 409
    state.jobs.unshift({
      id: 'job_late',
      version_id: 'v_va_9',
      document_id: VA,
      status: 'queued',
      attempt: 1,
      stage: 'queued',
      error: null,
      queued_at: new Date().toISOString(),
      started_at: null,
      finished_at: null,
    });
    await user.click(within(dialog).getByRole('button', { name: 'Remove from index' }));

    expect(
      await screen.findByText('Could not remove the document from the index'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('An indexing job for this document is queued or running.'),
    ).toBeInTheDocument();
    expect(state.documents.find((d) => d.id === VA)!.active_version).not.toBeNull();
  });
});
