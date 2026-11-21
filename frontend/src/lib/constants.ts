export const MIN_QUESTION = 3;
export const MAX_QUESTION = 2000;
export const MAX_COMMENT = 1000;
export const MIN_PASSWORD = 10;
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

/** Rotating messages shown while an answer is pending (kept from v1). */
export const LOADING_MESSAGES = [
  'Searching policy and guidance documents…',
  'Checking formulary and PDL tables…',
  'Reading the most relevant pages…',
  'Drafting a cited answer…',
] as const;

export const EXAMPLE_QUESTIONS = [
  'Is Trulicity preferred under NY Medicaid?',
  'What is the prior authorization process?',
  'Should a DPP-4 inhibitor continue after mealtime insulin is added?',
  'Is this dosage form on the VA formulary?',
] as const;

export const REVIEW_WARNING = 'Please have a pharmacist review this answer before acting.';
export const NO_CITATIONS = 'No supporting citation was returned. Pharmacist review is required.';
export const FLAGGED_CITATION_WARNING =
  'This citation could not be matched to a page the assistant retrieved. Verify it in the source document.';

export const FEEDBACK_REASONS: Array<{
  value: 'wrong' | 'incomplete' | 'outdated' | 'unclear' | 'other';
  label: string;
}> = [
  { value: 'wrong', label: 'Wrong' },
  { value: 'incomplete', label: 'Incomplete' },
  { value: 'outdated', label: 'Outdated' },
  { value: 'unclear', label: 'Unclear' },
  { value: 'other', label: 'Other' },
];

export const PROGRAMS = ['VA', 'Medicare Part D', 'NY Medicaid'] as const;
export const AUTHORITIES = ['binding', 'advisory'] as const;
export const DOC_TYPES = ['policy', 'guideline', 'formulary', 'pdl', 'manual', 'other'] as const;

export const JOB_STAGES = [
  'queued',
  'parsing',
  'extracting_figures',
  'chunking',
  'embedding',
  'verifying',
  'active',
] as const;

export const STAGE_LABELS: Record<string, string> = {
  queued: 'Queued',
  parsing: 'Parsing',
  extracting_figures: 'Extracting figures',
  chunking: 'Chunking',
  embedding: 'Embedding',
  verifying: 'Verifying',
  active: 'Active',
  failed: 'Failed',
  superseded: 'Superseded',
  running: 'Running',
  done: 'Done',
};
