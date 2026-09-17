import { getBrandAccentOverride, getBrandTheme } from "@/lib/brand";
import { buildBrandCss, resolveThemePreset } from "@/lib/brand-themes";

/**
 * CSS variable overrides for white-label installations (HRP-393, HRP-463).
 *
 * Renders nothing on a default build, so the stock theme ships untouched.
 * Server component: the getters read the live container env on every SSR
 * pass — the root layout is already dynamic via RuntimeEnvScript's
 * headers() call.
 *
 * Two independent inputs compose here (see buildBrandCss):
 *  - NEXT_PUBLIC_BRAND_THEME picks a full token preset (lib/brand-themes).
 *  - NEXT_PUBLIC_BRAND_ACCENT_COLOR recolors the accent only, on top of the
 *    preset when both are set.
 *
 * A tenant's own preset / accent (HRP-808) lands on top of this block via
 * TenantBrandStyle in the authenticated layouts.
 */
export function BrandStyle() {
  const css = buildBrandCss(
    resolveThemePreset(getBrandTheme()),
    getBrandAccentOverride(),
  );
  return css ? <style>{css}</style> : null;
}
