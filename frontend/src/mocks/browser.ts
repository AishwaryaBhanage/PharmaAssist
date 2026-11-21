import { setupWorker } from 'msw/browser';
import { handlers, resetMocks } from './handlers';

// Browser mocks run with a little latency so loading states are visible.
resetMocks({ latency: 350 });

export const worker = setupWorker(...handlers);
