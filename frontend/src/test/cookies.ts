/** The script-readable cookie the server sets on sign-in; its presence says a session exists
 * (the real refresh cookie is HttpOnly, so tests never see it either). */
export function setSessionCookie(value = 'csrf-1'): void {
  document.cookie = `csrf_token=${value}; path=/`;
}

export function clearSessionCookie(): void {
  document.cookie = 'csrf_token=; path=/; max-age=0';
}
