import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios';
import { API_BASE_URL } from './config';
import { toApiError } from './errors';
import { tokens } from './tokens';

export const http = axios.create({ baseURL: API_BASE_URL, timeout: 120_000 });

/** Called when the session can no longer be refreshed (expired or revoked). */
let onSessionExpired: () => void = () => undefined;
export function setSessionExpiredHandler(handler: () => void): void {
  onSessionExpired = handler;
}

interface TokenResponse {
  access_token: string;
  refresh_token: string;
}

let refreshing: Promise<string> | null = null;

/** Exchange the refresh token for a new pair. Concurrent callers share one request, which
 * matters because refresh tokens are single-use. */
export function refreshSession(): Promise<string> {
  if (!refreshing) {
    const refresh = tokens.getRefresh();
    if (!refresh) return Promise.reject(new Error('no refresh token'));
    refreshing = axios
      .post<TokenResponse>(`${API_BASE_URL}/auth/refresh`, { refresh_token: refresh })
      .then(({ data }) => {
        tokens.set(data.access_token, data.refresh_token);
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
  return config;
});

type Retriable = InternalAxiosRequestConfig & { _retried?: boolean };

http.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as Retriable | undefined;
    const isAuthCall = original?.url?.startsWith('/auth/') ?? false;
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
