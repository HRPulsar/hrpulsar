import {
  SAFE_CSS_COLOR,
  getBrandAccentOverride,
  getBrandTheme,
} from "@/lib/brand";
import { resolveThemePreset } from "@/lib/brand-themes";

/**
 * CSS variable overrides for white-label installations (HRP-393, HRP-463).
 *
 * Renders nothing on a default build, so the stock theme ships untouched.
 * Server component: the getters read the live container env on every SSR
 * pass — the root layout is already dynamic via RuntimeEnvScript's
 * headers() call.
 *
 * Two independent inputs compose here:
 *  - NEXT_PUBLIC_BRAND_THEME picks a full token preset (lib/brand-themes).
 *    Light tokens go under `:root:root` (specificity 0,2,0 — outranks the
 *    stock `:root`), dark tokens under `.dark:root:root` (0,3,0 — outranks
 *    both `.dark` and the light injection; next-themes puts `.dark` on the
 *    same <html> element).
 *  - NEXT_PUBLIC_BRAND_ACCENT_COLOR recolors the accent only. When both are
 *    set, the accent is merged INTO both preset maps so it wins in dark mode
 *    too (a separate lower-specificity block would lose to `.dark:root:root`).
 *
 * Hover/deep shades for a custom accent are derived with color-mix; the
 * stock #0052CC/#003C99 shades stay hardcoded in globals.css for the
 * default build.
 */

// Token names we ever emit: standard custom-property syntax only.
const SAFE_TOKEN_NAME = /^--[a-z0-9-]+$/;

// --radius is a length, not a color — validated separately.
const SAFE_CSS_LENGTH = /^\d+(\.\d+)?(px|rem)$/;

function accentVars(accent: string): Record<string, string> {
  return {
    "--brand-accent": accent,
    "--brand-accent-hover": `color-mix(in oklab, ${accent} 85%, black)`,
    "--brand-accent-deep": `color-mix(in oklab, ${accent} 60%, black)`,
    "--accent": accent,
    "--ring": accent,
    "--sidebar-primary": accent,
    "--sidebar-ring": accent,
    "--chart-1": accent,
  };
}

function serializeVars(vars: Record<string, string>): string {
  let out = "";
  for (const [name, value] of Object.entries(vars)) {
    if (!SAFE_TOKEN_NAME.test(name)) continue;
    const valid =
      name === "--radius"
        ? SAFE_CSS_LENGTH.test(value)
        : SAFE_CSS_COLOR.test(value);
    if (valid) out += `${name}: ${value};`;
  }
  return out;
}

export function BrandStyle() {
  const rawAccent = getBrandAccentOverride();
  const accent =
    rawAccent && SAFE_CSS_COLOR.test(rawAccent) ? rawAccent : undefined;
  const preset = resolveThemePreset(getBrandTheme());

  if (!preset && !accent) return null;

  if (!preset) {
    // eslint-disable-next-line react/jsx-no-literals -- CSS template, not user copy
    return <style>{`:root:root {${serializeVars(accentVars(accent!))}}`}</style>;
  }

  const overlay = accent ? accentVars(accent) : undefined;
  const light = overlay ? { ...preset.light, ...overlay } : preset.light;
  const dark = overlay ? { ...preset.dark, ...overlay } : preset.dark;
  const css =
    `:root:root {${serializeVars(light)}}` +
    `.dark:root:root {${serializeVars(dark)}}`;
  return <style>{css}</style>;
}
