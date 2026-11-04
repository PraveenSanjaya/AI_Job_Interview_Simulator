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

const notFound = (what: string) =>
  errorBody('source_not_connected', `No ${what} source is connected`, 404);

/** The data endpoints the dashboard reads, for an account with no data yet. */
export function emptyAccountDataHandlers(): HttpHandler[] {
  return [
    http.get(api('/profile'), () =>
      HttpResponse.json({
        email: 'ada@example.com',
        full_name: 'Ada Lovelace',
        headline: null,
        career_objective: null,
        experience_level: null,
        preferred_difficulty: null,
        preferred_roles: [],
        education: [],
        work_experience: [],
        skills: [],
        projects: [],
        certifications: [],
        updated_at: '2026-01-01T00:00:00Z',
      }),
    ),
    http.get(api('/resumes'), () => HttpResponse.json([])),
    http.get(api('/jobs'), () => HttpResponse.json([])),
    http.get(api('/interviews'), () => HttpResponse.json([])),
    http.get(api('/integrations/github'), () => notFound('github')),
    http.get(api('/integrations/portfolio'), () => notFound('portfolio')),
  ];
}

/** A signed-in user with an empty account. */
export function emptyAccountHandlers(): HttpHandler[] {
  return [...signedInHandlers(), ...emptyAccountDataHandlers()];
}
