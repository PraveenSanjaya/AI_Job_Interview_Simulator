import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios';
import { withRefreshLock } from './authSync';
import { API_BASE_URL } from './config';
import { toApiError } from './errors';
import { CSRF_HEADER, readCsrfToken } from './session';
import { tokens } from './tokens';

// withCredentials: the refresh cookie is sent (and cleared) across origins when the API is
// not on the same origin as the page; the server only allows credentials for its own
// configured front-end origins.
export const http = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120_000,
  withCredentials: true,
});

/** Called when the session can no longer be refreshed (expired or revoked). */
let onSessionExpired: () => void = () => undefined;
export function setSessionExpiredHandler(handler: () => void): void {
  onSessionExpired = handler;
}

interface AccessTokenResponse {
  access_token: string;
}

/** Endpoints that act on the refresh cookie and therefore need the CSRF header. */
const COOKIE_ENDPOINTS = new Set(['/auth/refresh', '/auth/logout']);

export function csrfHeaders(): Record<string, string> {
  const token = readCsrfToken();
  return token ? { [CSRF_HEADER]: token } : {};
}

let refreshing: Promise<string> | null = null;

/** Exchange the refresh cookie for a new access token (the cookie is rotated by the server).
 * Callers in this tab share one request, and tabs take turns through a lock, because the
 * refresh token is single-use. */
export function refreshSession(): Promise<string> {
  if (!refreshing) {
    refreshing = withRefreshLock(() =>
      axios.post<AccessTokenResponse>(`${API_BASE_URL}/auth/refresh`, undefined, {
        withCredentials: true,
        headers: csrfHeaders(),
      }),
    )
      .then(({ data }) => {
        tokens.set(data.access_token);
        return data.access_token;
      })
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

http.interceptors.request.use((config) => {
  const access = tokens.getAccess();
  if (access) config.headers.set('Authorization', `Bearer ${access}`);
  if (config.url && COOKIE_ENDPOINTS.has(config.url)) {
    for (const [name, value] of Object.entries(csrfHeaders())) config.headers.set(name, value);
  }
  return config;
});

type Retriable = InternalAxiosRequestConfig & { _retried?: boolean };

http.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as Retriable | undefined;
    // Sign-in, refresh and logout must never trigger a refresh; the account deletion call
    // is an ordinary authenticated request and may.
    const isAuthCall =
      (original?.url?.startsWith('/auth/') ?? false) && original?.url !== '/auth/delete-account';
    if (error.response?.status === 401 && original && !original._retried && !isAuthCall) {
      original._retried = true;
      try {
        const access = await refreshSession();
        original.headers.set('Authorization', `Bearer ${access}`);
        return await http(original);
      } catch {
        tokens.clear();
        onSessionExpired();
      }
    }
    return Promise.reject(toApiError(error));
  },
);
