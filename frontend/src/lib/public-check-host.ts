/**
 * Where the public process check lives (HRP-918), read per request.
 *
 * The switch and the host are the backend's own PUBLIC_CHECK_ENABLED and
 * PUBLIC_CHECK_HOST from the site .env (HRP-920). Neither is NEXT_PUBLIC_:
 * the CI-built image knows no site, so only a server-side read of the
 * running container's env sees them - proxy.ts runs on the Node runtime and
 * the check pages render per request (connection()). Unset (on-prem,
 * Community) means no check pages at all and a proxy that behaves as before.
 *
 * Server-side only: in the browser every getter here reads nothing.
 */

const TRUE = /^(1|true|yes|on)$/i;

/** Bare lowercased host name of a host or URL ("" when unparsable):
 * "check.localhost:3410" and "https://check.hrpulsar.com/" alike. */
export function hostnameOf(value: string | null | undefined): string {
  const raw = (value ?? "").trim();
  if (!raw) return "";
  try {
    return new URL(raw.includes("://") ? raw : `http://${raw}`).hostname.toLowerCase();
  } catch {
    return "";
  }
}

/** Host name of the check, or "" while the service is off. */
export function publicCheckHost(): string {
  if (!TRUE.test((process.env.PUBLIC_CHECK_ENABLED ?? "").trim())) return "";
  return hostnameOf(process.env.PUBLIC_CHECK_HOST);
}

/** Does a request's Host header name the check host? */
export function isPublicCheckRequest(hostHeader: string | null | undefined): boolean {
  const host = publicCheckHost();
  return host !== "" && hostnameOf(hostHeader) === host;
}

/** Origin of the check host - the backend's rule (``public_check_origin``),
 * so the canonical URL here and the links in emails (HRP-926) agree. */
export function publicCheckOrigin(): string {
  if (!publicCheckHost()) return "";
  const host = (process.env.PUBLIC_CHECK_HOST ?? "").trim().replace(/\/+$/, "");
  return host.includes("://") ? host : `https://${host}`;
}

/** The canonical address of a result: `https://<check host>/r/<token>`,
 * the one emails and shares carry (HRP-926, HRP-928). */
export function canonicalResultUrl(token: string): string {
  const origin = publicCheckOrigin();
  return origin ? `${origin}/r/${encodeURIComponent(token)}` : "";
}

/** Origin of the app host, or "" when the site does not name one. http for
 * local names, https otherwise - the same rule as proxy.ts.
 *
 * NEXT_PUBLIC_APP_DOMAIN is inlined only into a build that has a value; the
 * CI image is built without one, so server code reads the container's value
 * (deploy/docker-compose.saas.yml) at run time - checked on a production
 * build, like NEXT_PUBLIC_MARKETING_DOMAIN in proxy.ts. */
export function appOrigin(): string {
  const domain = (process.env.NEXT_PUBLIC_APP_DOMAIN ?? "").trim();
  if (!domain) return "";
  const local = domain.includes("localhost") || domain.includes(".local");
  return `${local ? "http" : "https"}://${domain}`;
}
