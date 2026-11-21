import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { UploadDialog, validateFields, validateFile } from '@/components/admin/UploadDialog';
import { renderWithProviders } from './utils';

function fakeFile(name: string, size: number, type = 'application/pdf'): File {
  const f = new File([new Uint8Array(1)], name, { type });
  Object.defineProperty(f, 'size', { value: size });
  return f;
}

describe('UploadDialog validation', () => {
  it('rejects wrong types, empty and oversized files', () => {
    expect(validateFile(fakeFile('a.docx', 1000, 'application/msword'))).toMatch(
      /Only PDF and XLSX/,
    );
    expect(validateFile(fakeFile('a.pdf', 0))).toMatch(/empty/);
    expect(validateFile(fakeFile('a.pdf', 50 * 1024 * 1024 + 1))).toMatch(/limit is 50 MB/);
    expect(validateFile(fakeFile('a.pdf', 50 * 1024 * 1024))).toBeNull();
    expect(validateFile(fakeFile('sheet.xlsx', 1000, ''))).toBeNull();
  });

  it('validates the metadata fields', () => {
    const errs = validateFields({
      doc_id: 'Bad Slug',
      title: '',
      program: '',
      doc_type: '',
      authority: '',
      publisher: '',
      doc_date: '2025',
      source_url: 'ftp://x',
    });
    expect(Object.keys(errs).sort()).toEqual(
      [
        'authority',
        'doc_date',
        'doc_id',
        'doc_type',
        'program',
        'publisher',
        'source_url',
        'title',
      ].sort(),
    );
    expect(
      validateFields({
        doc_id: 'ny_pdl_2025',
        title: 'NY PDL',
        program: 'NY Medicaid',
        doc_type: 'pdl',
        authority: 'binding',
        publisher: 'NYS DOH',
        doc_date: '2025-07-01',
        source_url: '',
      }),
    ).toEqual({});
  });

  it('shows inline errors on submit and suggests a slug from the title', async () => {
    const user = userEvent.setup({ applyAccept: false });
    renderWithProviders(<UploadDialog open onOpenChange={() => {}} />);
    await screen.findByRole('dialog');

    await user.click(screen.getByRole('button', { name: 'Upload and index' }));
    expect(await screen.findByText('Choose a PDF or XLSX file.')).toBeInTheDocument();
    expect(screen.getByText('Title is required.')).toBeInTheDocument();
    expect(screen.getByText('Choose a program.')).toBeInTheDocument();

    await user.type(screen.getByLabelText('Title'), 'VA National Formulary 2025');
    expect(screen.getByLabelText('Document id (slug)')).toHaveValue('va_national_formulary_2025');
    expect(screen.queryByText('Title is required.')).toBeNull();

    // editing the slug stops the auto-suggestion
    await user.clear(screen.getByLabelText('Document id (slug)'));
    await user.type(screen.getByLabelText('Document id (slug)'), 'vanf');
    await user.type(screen.getByLabelText('Title'), ' (draft)');
    expect(screen.getByLabelText('Document id (slug)')).toHaveValue('vanf');

    // picking a bad file reports it next to the drop zone
    await user.upload(
      screen.getByLabelText('Document file'),
      fakeFile('notes.txt', 100, 'text/plain'),
    );
    expect(await screen.findByText('Only PDF and XLSX files are accepted.')).toBeInTheDocument();
  });
});
