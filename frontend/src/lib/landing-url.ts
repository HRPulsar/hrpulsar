/**
 * Where "home" is for anonymous surfaces after the marketing split (HRP-389):
 * the marketing site when a marketing domain is configured (SaaS), otherwise
 * the app root ("/" → /login via the root redirect). Build-time inlined —
 * fine for the SaaS image, which receives NEXT_PUBLIC_* at build; community
 * builds have no marketing site and correctly fall back to "/".
 */
export function getLandingHref(): string {
  const domain = process.env.NEXT_PUBLIC_MARKETING_DOMAIN;
  if (!domain) return "/";
  const proto =
    domain.includes("localhost") || domain.includes(".local") ? "http" : "https";
  return `${proto}://${domain}`;
}
