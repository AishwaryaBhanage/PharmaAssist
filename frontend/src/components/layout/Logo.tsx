import { cn } from '@/lib/utils';

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      <span
        aria-hidden="true"
        className="relative inline-block size-7 shrink-0 rounded-md bg-primary"
      >
        <span className="absolute left-1/2 top-1/2 h-4 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-[2px] bg-primary-foreground" />
        <span className="absolute left-1/2 top-1/2 h-1.5 w-4 -translate-x-1/2 -translate-y-1/2 rounded-[2px] bg-primary-foreground" />
      </span>
      <span className="font-heading text-base font-semibold tracking-tight">PharmAssist</span>
    </span>
  );
}
