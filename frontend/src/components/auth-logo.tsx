import { getLandingHref } from "@/lib/landing-url";
import { getBrandName, getLogoUrl } from "@/lib/brand";

export function AuthLogo() {
  const brandName = getBrandName();
  return (
    <a href={getLandingHref()} aria-label={brandName} data-testid="auth-link-landing">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={getLogoUrl("dark")} alt={brandName} width={320} />
    </a>
  );
}
