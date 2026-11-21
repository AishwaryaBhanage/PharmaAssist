import { AlertTriangle } from 'lucide-react';
import { useReadiness } from '@/api/queries';

/** Polls /health/ready while the API is not ready and shows what is missing. */
export function ReadinessBanner() {
  const { data, isError } = useReadiness();
  if (data?.ready) return null;
  const failing = data
    ? Object.entries(data.checks)
        .filter(([, ok]) => !ok)
        .map(([k]) => k)
    : [];
  const text =
    isError || !data
      ? 'The assistant is unavailable right now. Retrying…'
      : failing.length
        ? `The assistant is preparing (${failing.join(', ')} not ready). Questions are paused until it is.`
        : 'The assistant is preparing. Questions are paused until it is ready.';
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex shrink-0 items-center gap-2 border-b border-amber-border bg-amber-bg px-4 py-1.5 text-[13px] font-medium text-amber"
    >
      <AlertTriangle className="size-4 shrink-0" aria-hidden="true" />
      {text}
    </div>
  );
}
