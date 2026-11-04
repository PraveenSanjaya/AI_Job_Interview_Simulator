import { setupServer } from 'msw/node';

/** Every test registers the API behaviour it needs; unhandled requests fail the test. */
export const server = setupServer();
