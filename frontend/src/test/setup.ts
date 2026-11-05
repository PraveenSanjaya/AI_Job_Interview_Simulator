import '@testing-library/jest-dom/vitest';
import { cleanup, configure } from '@testing-library/react';
import { afterAll, afterEach, beforeAll } from 'vitest';
import { tokens } from '@/lib/tokens';
import { server } from './server';

// Pages are loaded on demand; the first import of each can take a while to transform.
configure({ asyncUtilTimeout: 5000 });

// jsdom has no layout engine: charts only need these observers to exist.
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver = ResizeObserverStub;

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  tokens.clear();
  window.localStorage.clear();
});
afterAll(() => server.close());
