/**
 * Token storage.
 *
 * The short-lived access token lives only in memory. The refresh token is kept in
 * localStorage so a reload keeps you signed in: the API uses bearer tokens, not cookies.
 * Trade-off: any script running on this page could read it, which is why the app renders
 * all backend text as plain text (never HTML) and sets no third-party scripts.
 */
const REFRESH_KEY = 'ajis.refresh_token';

let accessToken: string | null = null;

export const tokens = {
  getAccess: (): string | null => accessToken,
  getRefresh(): string | null {
    try {
      return window.localStorage.getItem(REFRESH_KEY);
    } catch {
      return null;
    }
  },
  set(access: string, refresh: string): void {
    accessToken = access;
    try {
      window.localStorage.setItem(REFRESH_KEY, refresh);
    } catch {
      /* storage unavailable: the session simply will not survive a reload */
    }
  },
  clear(): void {
    accessToken = null;
    try {
      window.localStorage.removeItem(REFRESH_KEY);
    } catch {
      /* ignore */
    }
  },
};
