import type {
  AdminMessageOut,
  CacheStatsOut,
  CitationOut,
  ConversationOut,
  DayStatOut,
  DocumentOut,
  HealthOut,
  JobOut,
  MessageOut,
  StatsOut,
  UserOut,
  VersionOut,
} from '@/api/types';
import { NO_ANSWER_TEXT } from '@/api/types';

const DAY = 24 * 3600 * 1000;
const now = Date.now();
const iso = (msAgo: number) => new Date(now - msAgo).toISOString();

// ---------------------------------------------------------------- users

export interface MockUser extends UserOut {
  password: string;
}

export const users: MockUser[] = [
  {
    id: 'u_admin',
    email: 'admin@pharmassist.local',
    display_name: 'Priya Natarajan',
    role: 'admin',
    is_active: true,
    created_at: iso(90 * DAY),
    last_login_at: iso(2 * 3600 * 1000),
    password: 'admin-password-1',
  },
  {
    id: 'u_dana',
    email: 'dana@pharmassist.local',
    display_name: 'Dana Whitfield',
    role: 'staff',
    is_active: true,
    created_at: iso(60 * DAY),
    last_login_at: iso(5 * 3600 * 1000),
    password: 'staff-password-1',
  },
  {
    id: 'u_marcus',
    email: 'marcus@pharmassist.local',
    display_name: 'Marcus Lee',
    role: 'staff',
    is_active: true,
    created_at: iso(45 * DAY),
    last_login_at: iso(1 * DAY),
    password: 'staff-password-1',
  },
  {
    id: 'u_sofia',
    email: 'sofia@pharmassist.local',
    display_name: 'Sofia Reyes',
    role: 'staff',
    is_active: false,
    created_at: iso(30 * DAY),
    last_login_at: iso(12 * DAY),
    password: 'staff-password-1',
  },
];

export function publicUser(u: MockUser): UserOut {
  const { password: _pw, ...rest } = u;
  void _pw;
  return rest;
}

// ---------------------------------------------------------------- documents

function version(
  partial: Partial<VersionOut> & Pick<VersionOut, 'id' | 'document_id'>,
): VersionOut {
  return {
    file_name: `${partial.document_id}.pdf`,
    content_type: 'application/pdf',
    bytes: 2_400_000,
    pages: 120,
    status: 'active',
    error: null,
    chunk_count: 480,
    figure_count: 0,
    created_at: iso(40 * DAY),
    activated_at: iso(40 * DAY),
    ...partial,
  };
}

export const documents: DocumentOut[] = [
  {
    id: 'va_dod_cpg_opioids_2022',
    title:
      'VA/DoD Clinical Practice Guideline for the Use of Opioids in the Management of Chronic Pain',
    program: 'VA',
    doc_type: 'guideline',
    authority: 'advisory',
    publisher: 'U.S. Department of Veterans Affairs',
    doc_date: '2022-05-01',
    source_url: 'https://www.healthquality.va.gov/guidelines/Pain/cot/',
    active_version: version({
      id: 'v_va_1',
      document_id: 'va_dod_cpg_opioids_2022',
      pages: 164,
      chunk_count: 612,
      figure_count: 7,
      bytes: 3_900_000,
    }),
    latest_version: version({
      id: 'v_va_1',
      document_id: 'va_dod_cpg_opioids_2022',
      pages: 164,
      chunk_count: 612,
      figure_count: 7,
      bytes: 3_900_000,
    }),
    versions: 1,
  },
  {
    id: 'medicare_part_d_manual_ch6',
    title:
      'Medicare Prescription Drug Benefit Manual, Chapter 6: Part D Drugs and Formulary Requirements',
    program: 'Medicare Part D',
    doc_type: 'manual',
    authority: 'binding',
    publisher: 'Centers for Medicare & Medicaid Services',
    doc_date: '2016-01-15',
    source_url:
      'https://www.cms.gov/Medicare/Prescription-Drug-Coverage/PrescriptionDrugCovContra/Downloads/Part-D-Benefits-Manual-Chapter-6.pdf',
    active_version: version({
      id: 'v_pd_2',
      document_id: 'medicare_part_d_manual_ch6',
      pages: 88,
      chunk_count: 391,
    }),
    latest_version: version({
      id: 'v_pd_3',
      document_id: 'medicare_part_d_manual_ch6',
      status: 'failed',
      error: 'Parser error: page 41 image stream is corrupt (attempt 3 of 3)',
      chunk_count: 0,
      created_at: iso(2 * DAY),
      activated_at: null,
    }),
    versions: 3,
  },
  {
    id: 'ny_medicaid_pdl_2025',
    title: 'New York State Medicaid Preferred Drug List',
    program: 'NY Medicaid',
    doc_type: 'pdl',
    authority: 'binding',
    publisher: 'New York State Department of Health',
    doc_date: '2025-07-01',
    source_url: 'https://newyork.fhsc.com/downloads/providers/NYRx_PDP_PDL.pdf',
    active_version: version({
      id: 'v_ny_4',
      document_id: 'ny_medicaid_pdl_2025',
      file_name: 'ny_pdl_2025_07.xlsx',
      content_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      pages: null,
      chunk_count: 1_204,
      bytes: 910_000,
    }),
    latest_version: version({
      id: 'v_ny_4',
      document_id: 'ny_medicaid_pdl_2025',
      file_name: 'ny_pdl_2025_07.xlsx',
      content_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      pages: null,
      chunk_count: 1_204,
      bytes: 910_000,
    }),
    versions: 4,
  },
  {
    // Removed from the index: the file is kept, so "Re-index" stays available.
    id: 'va_national_formulary_2024',
    title: 'VA National Formulary',
    program: 'VA',
    doc_type: 'formulary',
    authority: 'binding',
    publisher: 'VA Pharmacy Benefits Management Services',
    doc_date: '2024-11-01',
    source_url: 'https://www.va.gov/formularyadvisor/',
    active_version: null,
    latest_version: version({
      id: 'v_vanf_1',
      document_id: 'va_national_formulary_2024',
      file_name: 'va_national_formulary_2024_11.xlsx',
      content_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      pages: null,
      status: 'superseded',
      chunk_count: 0,
      bytes: 640_000,
      created_at: iso(25 * DAY),
      activated_at: null,
    }),
    versions: 1,
  },
];

// ---------------------------------------------------------------- jobs

export const jobs: JobOut[] = [
  {
    id: 'job_1',
    version_id: 'v_pd_3',
    document_id: 'medicare_part_d_manual_ch6',
    status: 'failed',
    attempt: 3,
    stage: 'parsing',
    error: 'Parser error: page 41 image stream is corrupt (attempt 3 of 3)',
    queued_at: iso(2 * DAY),
    started_at: iso(2 * DAY - 60_000),
    finished_at: iso(2 * DAY - 300_000),
  },
  {
    id: 'job_2',
    version_id: 'v_ny_4',
    document_id: 'ny_medicaid_pdl_2025',
    status: 'active',
    attempt: 1,
    stage: 'active',
    error: null,
    queued_at: iso(10 * DAY),
    started_at: iso(10 * DAY - 30_000),
    finished_at: iso(10 * DAY - 600_000),
  },
  {
    id: 'job_3',
    version_id: 'v_va_2',
    document_id: 'va_dod_cpg_opioids_2022',
    status: 'running',
    attempt: 1,
    stage: 'queued',
    error: null,
    queued_at: iso(20_000),
    started_at: null,
    finished_at: null,
  },
];

// ---------------------------------------------------------------- conversations

const vaCitation: CitationOut = {
  id: 'va_dod_cpg_opioids_2022:p27',
  doc_id: 'va_dod_cpg_opioids_2022',
  document:
    'VA/DoD Clinical Practice Guideline for the Use of Opioids in the Management of Chronic Pain',
  label: 'Page 27',
  page: 27,
  url: 'https://www.healthquality.va.gov/guidelines/Pain/cot/VADoDOpioidsCPG.pdf#page=27',
  local_url: '/api/v1/sources/va_dod_cpg_opioids_2022/p27.pdf',
  flagged: false,
  figures: [
    {
      figure_id: 'p027_f1',
      kind: 'algorithm',
      title: 'Module A: Determination of appropriateness of opioid therapy',
      status: 'machine_interpreted',
      status_text:
        'Text drawn from it is a machine-generated interpretation (machine-interpreted). Check it against the page.',
      crop_url: '/api/v1/figures/va_dod_cpg_opioids_2022/p027_f1.png',
    },
  ],
};

const nyCitation: CitationOut = {
  id: 'ny_medicaid_pdl_2025:GLP-1:row12',
  doc_id: 'ny_medicaid_pdl_2025',
  document: 'New York State Medicaid Preferred Drug List',
  label: 'GLP-1 Agonists sheet, row 12',
  sheet: 'GLP-1 Agonists',
  row: 12,
  url: null,
  local_url: null,
  flagged: false,
  figures: [],
};

const flaggedCitation: CitationOut = {
  id: 'medicare_part_d_manual_ch6:p99',
  doc_id: 'medicare_part_d_manual_ch6',
  document:
    'Medicare Prescription Drug Benefit Manual, Chapter 6: Part D Drugs and Formulary Requirements',
  label: 'Page 99',
  page: 99,
  url: null,
  local_url: null,
  flagged: true,
  flag_reason: 'Page 99 was not among the pages the assistant read; the document has 88 pages.',
  figures: [],
};

function message(
  partial: Partial<MessageOut> &
    Pick<MessageOut, 'message_id' | 'conversation_id' | 'question' | 'answer'>,
): MessageOut {
  return {
    request_id: `req_${partial.message_id}`,
    status: 'answered',
    assumption: null,
    citations: [],
    conflicts_noted: [],
    needs_review: false,
    cached: false,
    cache_similarity: null,
    matched_question: null,
    provider: 'openai',
    model: 'gpt-5.5',
    fallback_used: false,
    latency_seconds: 9.4,
    created_at: iso(3 * 3600 * 1000),
    feedback: null,
    ...partial,
  };
}

export const conversations: ConversationOut[] = [
  {
    id: 'c_1',
    title: 'Is Trulicity preferred under NY Medicaid?',
    created_at: iso(2 * DAY),
    updated_at: iso(3 * 3600 * 1000),
    message_count: 2,
    messages: [
      message({
        message_id: 'm_1',
        conversation_id: 'c_1',
        question: 'Is Trulicity preferred under NY Medicaid?',
        answer:
          '**Yes.** Dulaglutide (Trulicity) is a **preferred** GLP-1 agonist on the NYRx Medicaid PDL and does not need PA for members who meet the step criteria.\n\n| Drug | Status | PA |\n|---|---|---|\n| Trulicity (dulaglutide) | Preferred | No, after metformin trial |\n| Ozempic (semaglutide) | Preferred | No, after metformin trial |\n| Victoza (liraglutide) | Non-preferred | Yes |\n\n1. Confirm a 90-day metformin trial (or contraindication) in the record.\n2. Dispense; no PA form is needed.',
        citations: [nyCitation],
        created_at: iso(2 * DAY),
        latency_seconds: 11.2,
        feedback: {
          message_id: 'm_1',
          rating: 'helpful',
          reason: null,
          comment: null,
          created_at: iso(2 * DAY - 60_000),
          updated_at: iso(2 * DAY - 60_000),
        },
      }),
      message({
        message_id: 'm_2',
        conversation_id: 'c_1',
        question: 'Does Trulicity need prior auth on NY Medicaid?',
        answer:
          '**No PA** is required for Trulicity (dulaglutide) on the NYRx PDL once the metformin step is met.\n\n- Preferred GLP-1 agonists: Trulicity, Ozempic, Bydureon BCise.\n- Non-preferred (PA required): Victoza, Adlyxin.\n\nIf the member has not trialled metformin, the claim rejects with a step-therapy edit; submit the PA with the contraindication documented.',
        citations: [nyCitation],
        cached: true,
        cache_similarity: 0.93,
        matched_question: 'Is Trulicity preferred under NY Medicaid?',
        provider: 'cache',
        model: null,
        latency_seconds: 0.4,
        created_at: iso(3 * 3600 * 1000),
      }),
    ],
  },
  {
    id: 'c_2',
    title: 'Opioid taper guidance for a veteran on 90 MME',
    created_at: iso(5 * DAY),
    updated_at: iso(5 * DAY - 400_000),
    message_count: 2,
    messages: [
      message({
        message_id: 'm_3',
        conversation_id: 'c_2',
        question: 'What does the VA guideline say about tapering a veteran stable on 90 MME/day?',
        answer:
          'The VA/DoD CPG recommends an **individualised, collaborative taper** rather than a fixed schedule, and advises against abrupt discontinuation.\n\n1. Reassess risk/benefit; if risks outweigh benefits, offer a taper.\n2. Start with a 5–20% reduction every 4 weeks; slower (for example 2–10% monthly) for long-term use.\n3. Pause or slow the taper for withdrawal or worsening function; do not reverse to a higher dose.\n4. Offer non-opioid and non-pharmacologic pain care and monitor for suicidality.\n\nModule A on page 27 (algorithm) frames when therapy remains appropriate.',
        assumption: 'Program inferred as VA from "veteran"; the question did not name one.',
        citations: [vaCitation, flaggedCitation],
        conflicts_noted: [
          'VA/DoD CPG (2022, advisory) vs Medicare Part D manual (2016, binding): the clinical question follows the guideline (rule 3); the Part D manual covers coverage, not tapering.',
        ],
        needs_review: true,
        provider: 'anthropic',
        model: 'claude-sonnet-5-5',
        fallback_used: true,
        latency_seconds: 18.7,
        created_at: iso(5 * DAY),
        feedback: {
          message_id: 'm_3',
          rating: 'unhelpful',
          reason: 'incomplete',
          comment: 'Did not mention naloxone co-prescribing.',
          created_at: iso(5 * DAY - 120_000),
          updated_at: iso(5 * DAY - 120_000),
        },
      }),
      message({
        message_id: 'm_4',
        conversation_id: 'c_2',
        question: 'Is buprenorphine patch covered on the Oregon Medicaid PDL?',
        answer: NO_ANSWER_TEXT,
        status: 'no_answer',
        citations: [],
        latency_seconds: 6.1,
        created_at: iso(5 * DAY - 400_000),
      }),
    ],
  },
];

export const adminMessages: AdminMessageOut[] = conversations
  .flatMap((c) => c.messages)
  .map((m, i) => ({
    ...m,
    user_id: i % 2 === 0 ? 'u_dana' : 'u_marcus',
    user_email: i % 2 === 0 ? 'dana@pharmassist.local' : 'marcus@pharmassist.local',
    agent_status: m.status === 'no_answer' ? 'not_found' : 'answered',
    cost_usd: m.cached ? 0 : 0.0184 + i * 0.003,
    tokens: (m.cached ? {} : { input: 18_420 + i * 900, output: 612 + i * 40 }) as Record<
      string,
      number
    >,
    trace_id: m.cached ? null : `tr_${m.message_id}`,
  }));

// ---------------------------------------------------------------- stats

function seeded(n: number): () => number {
  let s = n;
  return () => {
    s = (s * 9301 + 49297) % 233280;
    return s / 233280;
  };
}

export function perDay(days = 30): DayStatOut[] {
  const rnd = seeded(42);
  const out: DayStatOut[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now - i * DAY);
    const weekend = d.getDay() === 0 || d.getDay() === 6;
    const questions = Math.round((weekend ? 6 : 24) + rnd() * (weekend ? 6 : 18));
    const helpful = Math.round(questions * (0.25 + rnd() * 0.2));
    const unhelpful = Math.round(questions * (0.03 + rnd() * 0.06));
    out.push({
      day: d.toISOString().slice(0, 10),
      questions,
      helpful,
      unhelpful,
      no_answer: Math.round(questions * (0.06 + rnd() * 0.08)),
      cached: Math.round(questions * (0.2 + rnd() * 0.2)),
    });
  }
  return out;
}

export const cacheStats: CacheStatsOut = {
  entries: 312,
  hits: 188,
  misses: 541,
  hit_rate: 188 / (188 + 541),
  threshold: 0.9,
  generation: 7,
  backend: 'valkey-knn',
};

export function stats(days = 30): StatsOut {
  const pd = perDay(days);
  const sum = (k: keyof DayStatOut) => pd.reduce((a, d) => a + (d[k] as number), 0);
  const questions = sum('questions');
  const noAnswer = sum('no_answer');
  return {
    since: new Date(now - days * DAY).toISOString(),
    until: new Date(now).toISOString(),
    questions,
    answered: questions - noAnswer,
    no_answer: noAnswer,
    cached: sum('cached'),
    fallback: 14,
    helpful: sum('helpful'),
    unhelpful: sum('unhelpful'),
    latency_p50_s: 8.6,
    latency_p95_s: 21.3,
    spend_usd: 61.4,
    spend_cap_usd: 10,
    spend_today_usd: 2.37,
    active_users: 3,
    users_total: users.length,
    documents_active: documents.filter((d) => d.active_version?.status === 'active').length,
    cache: { ...cacheStats },
    per_day: pd,
  };
}

export const health: HealthOut = {
  ready: true,
  checks: { postgres: true, cache: true, storage: true, llm_config: true },
  version: '2.0.0-mock',
  generation: 7,
};

/** A canned answer for new questions in mock mode. */
export function answerFor(
  question: string,
): Pick<
  MessageOut,
  'answer' | 'status' | 'citations' | 'assumption' | 'conflicts_noted' | 'needs_review'
> {
  const q = question.toLowerCase();
  if (q.includes('oregon') || q.includes('weather') || q.includes('unknown')) {
    return {
      answer: NO_ANSWER_TEXT,
      status: 'no_answer',
      citations: [],
      assumption: null,
      conflicts_noted: [],
      needs_review: false,
    };
  }
  if (q.includes('va') || q.includes('veteran') || q.includes('opioid')) {
    return {
      answer:
        'Per the VA/DoD CPG, **avoid initiating long-term opioid therapy** for chronic non-cancer pain; when opioids are used, keep the dose as low as possible and reassess at least every 90 days.\n\n1. Check the PDMP and document the risk review.\n2. Co-prescribe naloxone at any dose with risk factors.\n3. Avoid concurrent benzodiazepines.',
      status: 'answered',
      citations: [vaCitation],
      assumption: q.includes('va')
        ? null
        : 'Program inferred as VA from "veteran"; the question did not name one.',
      conflicts_noted: [],
      needs_review: false,
    };
  }
  return {
    answer:
      '**Preferred on the NYRx PDL.** No PA is required once the step criteria are documented.\n\n| Item | Value |\n|---|---|\n| Status | Preferred |\n| PA | No (step: metformin) |\n| Quantity limit | 4 pens / 28 days |',
    status: 'answered',
    citations: [nyCitation],
    assumption:
      q.includes('medicaid') || q.includes('ny')
        ? null
        : 'Program assumed to be NY Medicaid; say "Part D" or "VA" to switch.',
    conflicts_noted: [],
    needs_review: false,
  };
}
