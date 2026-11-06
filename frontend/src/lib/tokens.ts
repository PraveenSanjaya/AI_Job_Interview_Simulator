/**
 * Access-token storage: in memory only.
 *
 * The refresh token is never visible to this code: the server keeps it in an HttpOnly cookie
 * (see lib/session.ts). A page reload therefore loses the access token and gets a new one
 * from the refresh endpoint, so nothing that can authenticate a request is ever written to
 * localStorage, sessionStorage or any other browser-readable storage.
 */
let accessToken: string | null = null;

export const tokens = {
  getAccess: (): string | null => accessToken,
  set(access: string): void {
    accessToken = access;
  },
  clear(): void {
    accessToken = null;
  },
};
