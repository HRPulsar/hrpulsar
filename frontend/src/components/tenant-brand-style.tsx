"use client";

import { useAuth } from "@/context/auth-context";
import { buildBrandCss, resolveThemePreset } from "@/lib/brand-themes";

/**
 * HRP-808: the tenant's theme preset / accent on top of the site's env
 * branding (BrandStyle in the root <head>).
 *
 * Mounted inside AuthProvider, which renders nothing but its loading screen
 * until /auth/me answers — so the first frame of the app already carries
 * the tenant colors and there is nothing to flash. A plain <style> (no
 * `precedence`) stays in place and unmounts with the layout, so surfaces
 * outside the tenant shells (/platform, auth pages) keep the site colors.
 */
export function TenantBrandStyle() {
  const { user } = useAuth();
  const accent = user?.tenant_brand_accent_color;
  const css = buildBrandCss(
    resolveThemePreset(user?.tenant_brand_theme ?? undefined),
    // The backend only stores #RRGGBB; hold the render to the same contract
    // rather than the looser site-env color check.
    accent && /^#[0-9a-fA-F]{6}$/.test(accent) ? accent : undefined,
  );
  return css ? <style>{css}</style> : null;
}
