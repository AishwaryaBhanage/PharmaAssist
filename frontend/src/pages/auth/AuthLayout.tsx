import type { ReactNode } from 'react';
import { Logo } from '@/components/layout/Logo';

export function AuthLayout({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center gap-3 text-center">
          <Logo />
          <div>
            <h1 className="text-xl font-semibold">{title}</h1>
            {subtitle ? <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p> : null}
          </div>
        </div>
        <div className="rounded-lg border bg-card p-6 shadow-xs">{children}</div>
        <p className="mt-6 text-center text-xs text-muted-foreground">
          Do not enter patient names, dates of birth, prescription numbers or other identifying
          information anywhere in PharmAssist.
        </p>
      </div>
    </main>
  );
}
