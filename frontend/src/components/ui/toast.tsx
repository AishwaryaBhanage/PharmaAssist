import * as React from 'react';
import { Toast as ToastPrimitive } from 'radix-ui';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';

export type ToastKind = 'default' | 'success' | 'error';

export interface ToastItem {
  id: number;
  title: string;
  description?: string;
  kind: ToastKind;
  /** an optional secondary action, e.g. "Copy request id" */
  action?: { label: string; onClick: () => void };
}

interface ToastContextValue {
  toast: (t: Omit<ToastItem, 'id'>) => void;
}

const ToastContext = React.createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = React.useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>');
  return ctx;
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = React.useState<ToastItem[]>([]);
  const nextId = React.useRef(1);

  const toast = React.useCallback((t: Omit<ToastItem, 'id'>) => {
    const id = nextId.current++;
    setItems((prev) => [...prev.slice(-3), { ...t, id }]);
  }, []);

  const dismiss = (id: number) => setItems((prev) => prev.filter((t) => t.id !== id));

  const value = React.useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      <ToastPrimitive.Provider swipeDirection="right" duration={6000}>
        {children}
        {items.map((t) => (
          <ToastPrimitive.Root
            key={t.id}
            onOpenChange={(open) => !open && dismiss(t.id)}
            className={cn(
              'group pointer-events-auto relative flex w-full items-start gap-3 overflow-hidden rounded-md border bg-card p-4 pr-8 shadow-lg data-[state=closed]:animate-out data-[state=closed]:fade-out-80 data-[swipe=end]:animate-out',
              t.kind === 'error' && 'border-destructive/40',
              t.kind === 'success' && 'border-success/40',
            )}
          >
            <div
              aria-hidden="true"
              className={cn(
                'mt-1 size-2 shrink-0 rounded-full',
                t.kind === 'error'
                  ? 'bg-destructive'
                  : t.kind === 'success'
                    ? 'bg-success'
                    : 'bg-primary',
              )}
            />
            <div className="grid gap-1 text-sm">
              <ToastPrimitive.Title className="font-semibold">{t.title}</ToastPrimitive.Title>
              {t.description ? (
                <ToastPrimitive.Description className="text-muted-foreground">
                  {t.description}
                </ToastPrimitive.Description>
              ) : null}
              {t.action ? (
                <ToastPrimitive.Action altText={t.action.label} asChild>
                  <button
                    type="button"
                    onClick={t.action.onClick}
                    className="mt-1 w-fit text-xs font-medium text-primary underline-offset-2 hover:underline"
                  >
                    {t.action.label}
                  </button>
                </ToastPrimitive.Action>
              ) : null}
            </div>
            <ToastPrimitive.Close
              className="absolute right-2 top-2 rounded-md p-1 opacity-60 hover:opacity-100 focus-visible:outline-2 focus-visible:outline-ring"
              aria-label="Dismiss"
            >
              <X className="size-4" />
            </ToastPrimitive.Close>
          </ToastPrimitive.Root>
        ))}
        <ToastPrimitive.Viewport className="fixed bottom-0 right-0 z-[100] flex max-h-screen w-full flex-col gap-2 p-4 sm:max-w-sm" />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  );
}
