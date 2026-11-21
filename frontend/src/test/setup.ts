import '@testing-library/jest-dom/vitest';
import { afterAll, afterEach, beforeAll } from 'vitest';
import { cleanup } from '@testing-library/react';
import { server } from '@/mocks/server';
import { resetMocks } from '@/mocks/handlers';
import { setAccessToken } from '@/api/token';

// Node's fetch rejects relative URLs and jsdom's AbortSignal. Resolve URLs against jsdom's location
// so MSW can match them, and emulate the signal by racing the request against it. Installed after
// server.listen() so it sits above MSW's own fetch patch.
function shimFetch(): void {
  const mswFetch = globalThis.fetch;
  globalThis.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    if (typeof input === 'string' && input.startsWith('/')) input = window.location.origin + input;
    const { signal, ...rest } = init ?? {};
    const pending = mswFetch(input, rest);
    if (!signal) return pending;
    return new Promise<Response>((resolve, reject) => {
      const abort = () => reject(new DOMException('The operation was aborted.', 'AbortError'));
      if (signal.aborted) return abort();
      signal.addEventListener('abort', abort, { once: true });
      pending.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort));
    });
  };
}

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' });
  shimFetch();
});
afterEach(() => {
  cleanup();
  server.resetHandlers();
  setAccessToken(null);
  sessionStorage.clear();
  localStorage.clear();
  resetMocks();
});
afterAll(() => server.close());

// jsdom lacks these; Radix and the chart touch them.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}
if (!Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = () => {};
if (!window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}
// Radix Select/Dropdown call pointer-capture APIs jsdom does not implement.
if (!Element.prototype.hasPointerCapture) Element.prototype.hasPointerCapture = () => false;
if (!Element.prototype.setPointerCapture) Element.prototype.setPointerCapture = () => {};
if (!Element.prototype.releasePointerCapture) Element.prototype.releasePointerCapture = () => {};
