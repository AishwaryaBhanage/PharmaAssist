import { useId, useState } from 'react';
import type { DayStatOut } from '@/api/types';

/**
 * Dependency-free SVG chart: bars for questions per day, lines for helpful and unhelpful ratings.
 * Hover/focus a day to read the exact numbers; the table under it is the accessible equivalent.
 */
export function DailyChart({ days }: { days: DayStatOut[] }) {
  const id = useId();
  const [active, setActive] = useState<number | null>(null);
  const W = 720;
  const H = 200;
  const padL = 32;
  const padR = 8;
  const padT = 10;
  const padB = 26;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;
  const n = Math.max(days.length, 1);
  const max = Math.max(1, ...days.map((d) => d.questions));
  const step = innerW / n;
  const barW = Math.max(2, step * 0.6);
  const y = (v: number) => padT + innerH - (v / max) * innerH;
  const x = (i: number) => padL + i * step + step / 2;
  const ticks = niceTicks(max);
  const line = (key: 'helpful' | 'unhelpful') =>
    days.map((d, i) => `${x(i).toFixed(1)},${y(d[key]).toFixed(1)}`).join(' ');
  const current = active != null ? days[active] : null;

  if (!days.length) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">No activity in this period.</p>
    );
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <LegendSwatch className="bg-primary/70" label="Questions" />
        <LegendSwatch className="bg-success" label="Helpful" line />
        <LegendSwatch className="bg-destructive" label="Unhelpful" line />
        <span className="ml-auto tabular-nums" aria-live="polite">
          {current
            ? `${current.day}: ${current.questions} questions · ${current.helpful} helpful · ${current.unhelpful} unhelpful · ${current.no_answer} no answer · ${current.cached} cached`
            : 'Hover a day for details'}
        </span>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="mt-2 h-auto w-full"
        role="img"
        aria-labelledby={`${id}-title`}
        onMouseLeave={() => setActive(null)}
      >
        <title id={`${id}-title`}>Questions and ratings per day</title>
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={padL}
              x2={W - padR}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--border)"
              strokeWidth="1"
            />
            <text
              x={padL - 6}
              y={y(t) + 3}
              textAnchor="end"
              fontSize="10"
              fill="var(--muted-foreground)"
            >
              {t}
            </text>
          </g>
        ))}
        {days.map((d, i) => (
          <g key={d.day}>
            <rect
              x={x(i) - barW / 2}
              y={y(d.questions)}
              width={barW}
              height={Math.max(0, padT + innerH - y(d.questions))}
              rx="1.5"
              fill="var(--primary)"
              opacity={active === null || active === i ? 0.7 : 0.35}
            />
            <rect
              x={padL + i * step}
              y={padT}
              width={step}
              height={innerH + padB}
              fill="transparent"
              tabIndex={0}
              onMouseEnter={() => setActive(i)}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
              aria-label={`${d.day}: ${d.questions} questions, ${d.helpful} helpful, ${d.unhelpful} unhelpful`}
            />
            {i % Math.ceil(n / 6) === 0 || i === n - 1 ? (
              <text
                x={x(i)}
                y={H - 8}
                textAnchor="middle"
                fontSize="10"
                fill="var(--muted-foreground)"
              >
                {d.day.slice(5)}
              </text>
            ) : null}
          </g>
        ))}
        <polyline
          points={line('helpful')}
          fill="none"
          stroke="var(--success)"
          strokeWidth="2"
          strokeLinejoin="round"
        />
        <polyline
          points={line('unhelpful')}
          fill="none"
          stroke="var(--destructive)"
          strokeWidth="2"
          strokeLinejoin="round"
        />
        {current && active != null ? (
          <line
            x1={x(active)}
            x2={x(active)}
            y1={padT}
            y2={padT + innerH}
            stroke="var(--foreground)"
            strokeOpacity="0.3"
            strokeDasharray="3 3"
          />
        ) : null}
      </svg>
    </div>
  );
}

function LegendSwatch({
  className,
  label,
  line,
}: {
  className: string;
  label: string;
  line?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        aria-hidden="true"
        className={`${line ? 'h-0.5 w-4' : 'size-2.5 rounded-sm'} ${className}`}
      />
      {label}
    </span>
  );
}

function niceTicks(max: number): number[] {
  const rough = max / 4;
  const pow = 10 ** Math.floor(Math.log10(rough || 1));
  const stepCandidates = [1, 2, 5, 10].map((m) => m * pow);
  const step = stepCandidates.find((s) => s >= rough) ?? pow * 10;
  const out: number[] = [];
  for (let v = 0; v <= max; v += step) out.push(v);
  return out;
}
