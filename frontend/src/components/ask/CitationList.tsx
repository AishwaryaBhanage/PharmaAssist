import { AlertTriangle, ExternalLink, FileText } from 'lucide-react';
import type { CitationOut } from '@/api/types';
import { FLAGGED_CITATION_WARNING, NO_CITATIONS } from '@/lib/constants';
import { isApiLink, openAuthorized } from '@/lib/links';
import { isAllowedHref } from '@/lib/markdown';
import { cn } from '@/lib/utils';
import { FigureNote } from './FigureNote';

export function citationHref(c: CitationOut): string | null {
  if (c.flagged) return null;
  if (c.local_url && isAllowedHref(c.local_url)) return c.local_url;
  if (c.url && isAllowedHref(c.url)) return c.url;
  return null;
}

export function CitationList({
  citations,
  compact,
}: {
  citations: CitationOut[];
  compact?: boolean;
}) {
  if (!citations.length) {
    return (
      <p
        role="note"
        className="rounded-md border border-amber-border bg-amber-bg px-3 py-2 text-sm font-medium text-amber"
      >
        {NO_CITATIONS}
      </p>
    );
  }
  return (
    <ol className="grid gap-1.5" aria-label="Citations">
      {citations.map((c, i) => (
        <CitationItem key={`${c.id}-${i}`} index={i + 1} citation={c} compact={compact} />
      ))}
    </ol>
  );
}

function CitationItem({
  index,
  citation: c,
  compact,
}: {
  index: number;
  citation: CitationOut;
  compact?: boolean;
}) {
  const href = citationHref(c);
  const title = c.document || 'Unknown document';
  const label =
    c.label ||
    (c.page != null ? `Page ${c.page}` : c.row != null ? `Row ${c.row}` : 'Location not available');
  const publisher = !c.flagged && c.url && isAllowedHref(c.url) && c.url !== href ? c.url : null;

  return (
    <li
      className={cn(
        'rounded-md border px-2.5 py-1.5 text-[13px] leading-snug',
        c.flagged ? 'border-amber-border bg-amber-bg/50 text-muted-foreground' : 'bg-card',
      )}
    >
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="text-xs tabular-nums text-muted-foreground">[{index}]</span>
        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => {
              if (isApiLink(href)) {
                e.preventDefault();
                void openAuthorized(href);
              }
            }}
            className="inline-flex items-center gap-1 font-medium text-foreground underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-ring"
          >
            <FileText className="size-3.5 text-muted-foreground" aria-hidden="true" />
            {title}
            <ExternalLink className="size-3 text-muted-foreground" aria-hidden="true" />
          </a>
        ) : (
          <span className={cn('font-medium', c.flagged && 'text-muted-foreground')}>{title}</span>
        )}
        <span
          className={cn(
            'text-xs font-medium',
            c.flagged ? 'text-muted-foreground' : 'text-primary',
          )}
        >
          {label}
        </span>
        {c.flagged ? (
          <span className="inline-flex items-center gap-1 text-xs font-semibold text-amber">
            <AlertTriangle className="size-3" aria-hidden="true" />
            Unverified
          </span>
        ) : null}
        {!compact && publisher ? (
          <a
            href={publisher}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-auto text-xs text-muted-foreground underline-offset-2 hover:underline"
          >
            Full document (publisher)
          </a>
        ) : null}
      </div>
      {c.flagged ? (
        <p className="mt-0.5 text-xs text-amber">{c.flag_reason || FLAGGED_CITATION_WARNING}</p>
      ) : null}
      {!compact && !c.flagged
        ? c.figures.map((f) => <FigureNote key={f.figure_id} figure={f} />)
        : null}
    </li>
  );
}
