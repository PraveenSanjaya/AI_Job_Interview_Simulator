/**
 * Helpers for the cookie-based session.
 *
 * The server sets two cookies on sign-in: an HttpOnly refresh cookie (invisible to scripts)
 * and a script-readable CSRF cookie. The CSRF cookie doubles as the "a session probably
 * exists" hint, so a signed-out visitor makes no pointless refresh request on page load.
 */
export const CSRF_COOKIE = 'csrf_token';
export const CSRF_HEADER = 'X-CSRF-Token';

/** Where the refresh token used to be kept before the cookie migration. */
const LEGACY_REFRESH_KEY = 'ajis.refresh_token';

export function readCsrfToken(): string | null {
  for (const part of document.cookie.split(';')) {
    const [name, ...rest] = part.trim().split('=');
    if (name === CSRF_COOKIE) return decodeURIComponent(rest.join('='));
  }
  return null;
}

export function hasSessionHint(): boolean {
  return readCsrfToken() !== null;
}

/** Delete a refresh token an older version of the app left in localStorage. Users who still
 * had one simply sign in again; the app never sends it to the server. */
export function purgeLegacyRefreshToken(): void {
  try {
    window.localStorage.removeItem(LEGACY_REFRESH_KEY);
    window.sessionStorage.removeItem(LEGACY_REFRESH_KEY);
  } catch {
    /* storage unavailable: nothing to purge */
  }
}
