import { useEffect } from 'react';

export function useDocumentTitle(title: string | null | undefined): void {
  useEffect(() => {
    const prev = document.title;
    document.title = title ? `${title} · PharmAssist` : 'PharmAssist';
    return () => {
      document.title = prev;
    };
  }, [title]);
}
