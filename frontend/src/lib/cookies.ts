/**
 * Browser-side cookie writes for the markers `proxy.ts` reads
 * (`has_token`, `demo_session`).
 *
 * `Secure` is conditional on purpose: local development runs on
 * http://localhost and the e2e stack in CI serves plain http, where a
 * browser silently drops a `Secure` cookie — every navigation would then
 * bounce back to /login. Over https the flag keeps the marker off
 * plaintext requests.
 */
export function setClientCookie(name: string, value: string): void {
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${name}=${value}; path=/; SameSite=Lax${secure}`;
}
