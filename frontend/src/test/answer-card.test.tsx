import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AnswerCard } from '@/components/ask/AnswerCard';
import { TooltipProvider } from '@/components/ui/tooltip';
import { conversations } from '@/mocks/fixtures';
import { NO_ANSWER_TEXT } from '@/api/types';

const cached = conversations[0]!.messages[1]!;
const noAnswer = conversations[1]!.messages[1]!;
const reviewed = conversations[1]!.messages[0]!;

function mount(ui: React.ReactElement) {
  return render(<TooltipProvider delayDuration={0}>{ui}</TooltipProvider>);
}

describe('AnswerCard', () => {
  it('renders the Cached badge with the matched question and similarity in a tooltip', async () => {
    const user = userEvent.setup();
    mount(<AnswerCard message={cached} />);
    const badge = screen.getByText('Cached');
    expect(badge).toBeInTheDocument();
    await user.hover(badge);
    const tips = await screen.findAllByText(
      'Matched: Is Trulicity preferred under NY Medicaid? (similarity 0.93)',
    );
    expect(tips.length).toBeGreaterThan(0);
    // provider "cache" is not shown as a model name; latency is
    expect(screen.getByText('0.4 s')).toBeInTheDocument();
  });

  it('renders the exact no-answer sentence as a neutral empty state, not an error', () => {
    mount(<AnswerCard message={noAnswer} />);
    expect(screen.getByText(NO_ANSWER_TEXT)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByText(/Citations/)).toBeNull();
  });

  it('treats any status with the no-answer text as no answer', () => {
    mount(
      <AnswerCard message={{ ...noAnswer, status: 'answered', answer: `  ${NO_ANSWER_TEXT} ` }} />,
    );
    expect(screen.getByText(NO_ANSWER_TEXT)).toBeInTheDocument();
  });

  it('shows the assumption banner, fallback badge, conflicts, flagged citation and figure note', () => {
    mount(<AnswerCard message={reviewed} />);
    expect(screen.getByText(/Program inferred as VA/)).toBeInTheDocument();
    expect(screen.getByText('Fallback model')).toBeInTheDocument();
    expect(screen.getByText('Needs pharmacist review')).toBeInTheDocument();
    expect(screen.getByText('Conflicts noted')).toBeInTheDocument();
    expect(screen.getByText('Unverified')).toBeInTheDocument();
    expect(screen.getByText(/Page 99 was not among the pages/)).toBeInTheDocument();
    expect(screen.getByText(/This page has a algorithm: Module A/)).toBeInTheDocument();
    const img = screen.getByRole('img', { name: /algorithm: Module A/ });
    expect(img).toHaveAttribute('loading', 'lazy');
    expect(img).toHaveAttribute('src', '/api/v1/figures/va_dod_cpg_opioids_2022/p027_f1.png');
    // the good citation opens local_url in a new tab
    const link = screen.getByRole('link', { name: /VA\/DoD Clinical Practice Guideline/ });
    expect(link).toHaveAttribute('href', '/api/v1/sources/va_dod_cpg_opioids_2022/p27.pdf');
    expect(link).toHaveAttribute('target', '_blank');
    expect(screen.getByText('anthropic · claude-sonnet-5-5 · 18.7 s')).toBeInTheDocument();
  });
});
