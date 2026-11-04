import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { http, HttpResponse, type HttpHandler } from 'msw';
import { MemoryRouter } from 'react-router-dom';
import { App } from '@/App';
import { AuthProvider } from '@/auth/AuthContext';
import { API_BASE_URL } from '@/lib/config';
import { tokens } from '@/lib/tokens';
import { server } from './server';

/** MSW pattern matching an API path whatever the test origin is. */
export const api = (path: string): string => `*${API_BASE_URL}${path}`;

export function renderApp(route = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter
        initialEntries={[route]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

export const USER = {
  id: 'u1',
  email: 'ada@example.com',
  role: 'user',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
};

export function errorBody(code: string, message: string, status: number, extra: object = {}) {
  return HttpResponse.json({ error: { code, message, request_id: 'req-1', ...extra } }, { status });
}

/** Pretend a previous visit left a valid session: refresh succeeds and /auth/me works. */
export function signedInHandlers(): HttpHandler[] {
  tokens.set('old-access', 'refresh-1');
  return [
    http.post(api('/auth/refresh'), () =>
      HttpResponse.json({
        access_token: 'access-1',
        refresh_token: 'refresh-2',
        token_type: 'bearer',
        expires_in: 1800,
      }),
    ),
    http.get(api('/auth/me'), () => HttpResponse.json(USER)),
  ];
}

export function useHandlers(...handlers: HttpHandler[]) {
  server.use(...handlers);
}
