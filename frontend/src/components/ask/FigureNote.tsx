import { useState } from 'react';
import { ImageIcon } from 'lucide-react';
import type { FigureOut } from '@/api/types';
import { authorizedHref, isApiLink, openAuthorized } from '@/lib/links';
import { isAllowedHref } from '@/lib/markdown';

const STATUS_LABEL: Record<string, string> = {
  machine_interpreted: 'machine-interpreted',
  ocr_checked: 'OCR-checked',
  reviewed: 'reviewed',
};

/** A figure note under a citation: what the figure is, how it was read, and the crop if there is one. */
export function FigureNote({ figure }: { figure: FigureOut }) {
  const [failed, setFailed] = useState(false);
  const kind = figure.kind || 'figure';
  const title = figure.title || 'Figure';
  const crop = figure.crop_url && isAllowedHref(figure.crop_url) ? figure.crop_url : null;
  const status = STATUS_LABEL[figure.status] ?? figure.status;

  return (
    <div className="mt-1.5 flex gap-2.5 rounded-md border border-dashed bg-card p-2 text-xs">
      {crop && !failed ? (
        <a
          href={crop}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => {
            if (isApiLink(crop)) {
              e.preventDefault();
              void openAuthorized(crop);
            }
          }}
          className="shrink-0 rounded-sm focus-visible:outline-2 focus-visible:outline-ring"
          aria-label={`Open the ${kind} image: ${title}`}
        >
          <img
            src={authorizedHref(crop)}
            alt={`${kind}: ${title}`}
            loading="lazy"
            decoding="async"
            onError={() => setFailed(true)}
            className="size-14 rounded-sm border object-cover"
          />
        </a>
      ) : (
        <div
          className="flex size-14 shrink-0 items-center justify-center rounded-sm border bg-muted text-muted-foreground"
          aria-hidden="true"
        >
          <ImageIcon className="size-5" />
        </div>
      )}
      <div className="min-w-0">
        <p className="font-medium">
          This page has a {kind}: {title}
        </p>
        <p className="text-muted-foreground">
          {figure.status_text ||
            `Text drawn from it is a machine-generated interpretation (${status}). Check it against the page.`}
        </p>
        {crop ? (
          <a
            href={crop}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => {
              if (isApiLink(crop)) {
                e.preventDefault();
                void openAuthorized(crop);
              }
            }}
            className="mt-1 inline-block font-medium text-primary underline-offset-2 hover:underline"
          >
            View the figure image
          </a>
        ) : null}
      </div>
    </div>
  );
}
