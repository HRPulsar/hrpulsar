/**
 * White-label brand configuration (HRP-393).
 *
 * Every getter falls back to the stock HRPulsar brand, so a build without
 * overrides is identical to the pre-white-label UI. Self-hosted operators
 * override via env (see docs "Self-hosted → Branding"):
 *
 *   NEXT_PUBLIC_BRAND_NAME           — installation name (metadata, UI copy)
 *   NEXT_PUBLIC_LOGO_URL             — logo for light backgrounds
 *   NEXT_PUBLIC_LOGO_DARK_URL        — logo for dark backgrounds (falls back
 *                                      to NEXT_PUBLIC_LOGO_URL)
 *   NEXT_PUBLIC_BRAND_ACCENT_COLOR   — accent color, any CSS color value
 *   NEXT_PUBLIC_FAVICON_URL          — favicon
 *   NEXT_PUBLIC_SIDEBAR_LOGO_HEIGHT  — sidebar logo height, e.g. "28px"
 *   NEXT_PUBLIC_BRAND_THEME          — theme preset name (lib/brand-themes.ts)
 *   NEXT_PUBLIC_BRAND_AUTH_BG_COLOR  — login/register background color
 *   NEXT_PUBLIC_BRAND_AUTH_BG_URL    — login/register background image URL
 */

export const DEFAULT_BRAND_NAME = "HRPulsar";
const DEFAULT_LOGO_LIGHT = "/brand/logo-horizontal-color-light.svg";
const DEFAULT_LOGO_DARK = "/brand/logo-horizontal-color.svg";
const DEFAULT_ACCENT = "#0066FF";
const DEFAULT_FAVICON = "/icon.svg";

/** Whitelist of characters valid in a CSS color (hex, rgb()/oklch()/named);
 * anything else (braces, semicolons) could escape a declaration block. */
export const SAFE_CSS_COLOR = /^[#a-zA-Z0-9(),.%\s/-]+$/;

/** Sidebar logo height override: a plain px/rem length, nothing else. */
const SAFE_CSS_LENGTH = /^\d+(\.\d+)?(px|rem)$/;

/** Auth background image: absolute http(s) or root-relative URL with no
 * characters that could escape a `url("…")` wrapper or an inline style. */
const SAFE_BG_URL = /^(https?:\/\/|\/)[^\s"'\\()<>]+$/;

type BrandEnvKey =
  | "NEXT_PUBLIC_BRAND_NAME"
  | "NEXT_PUBLIC_LOGO_URL"
  | "NEXT_PUBLIC_LOGO_DARK_URL"
  | "NEXT_PUBLIC_BRAND_ACCENT_COLOR"
  | "NEXT_PUBLIC_FAVICON_URL"
  | "NEXT_PUBLIC_SIDEBAR_LOGO_HEIGHT"
  | "NEXT_PUBLIC_BRAND_THEME"
  | "NEXT_PUBLIC_BRAND_AUTH_BG_COLOR"
  | "NEXT_PUBLIC_BRAND_AUTH_BG_URL";

/** Build-time inlined values, for client contexts without runtime
 * injection (local dev, build-args). Static member access per key is
 * required for the bundler to substitute them. */
function buildTimeEnv(key: BrandEnvKey): string | undefined {
  switch (key) {
    case "NEXT_PUBLIC_BRAND_NAME":
      return process.env.NEXT_PUBLIC_BRAND_NAME;
    case "NEXT_PUBLIC_LOGO_URL":
      return process.env.NEXT_PUBLIC_LOGO_URL;
    case "NEXT_PUBLIC_LOGO_DARK_URL":
      return process.env.NEXT_PUBLIC_LOGO_DARK_URL;
    case "NEXT_PUBLIC_BRAND_ACCENT_COLOR":
      return process.env.NEXT_PUBLIC_BRAND_ACCENT_COLOR;
    case "NEXT_PUBLIC_FAVICON_URL":
      return process.env.NEXT_PUBLIC_FAVICON_URL;
    case "NEXT_PUBLIC_SIDEBAR_LOGO_HEIGHT":
      return process.env.NEXT_PUBLIC_SIDEBAR_LOGO_HEIGHT;
    case "NEXT_PUBLIC_BRAND_THEME":
      return process.env.NEXT_PUBLIC_BRAND_THEME;
    case "NEXT_PUBLIC_BRAND_AUTH_BG_COLOR":
      return process.env.NEXT_PUBLIC_BRAND_AUTH_BG_COLOR;
    case "NEXT_PUBLIC_BRAND_AUTH_BG_URL":
      return process.env.NEXT_PUBLIC_BRAND_AUTH_BG_URL;
  }
}

function readEnv(key: BrandEnvKey): string | undefined {
  if (typeof window === "undefined") {
    // Server: dynamic access on purpose — a static process.env.NEXT_PUBLIC_*
    // member read is inlined at build time and would freeze prebuilt (GHCR)
    // images to the CI env (see runtime-env-script.tsx). The dynamic read
    // sees the live container env on every SSR pass, which also keeps SSR
    // output consistent with what clients read from window.__ENV__.
    return process.env[key] || undefined;
  }
  return window.__ENV__?.[key] || buildTimeEnv(key) || undefined;
}

export function getBrandName(): string {
  return readEnv("NEXT_PUBLIC_BRAND_NAME") || DEFAULT_BRAND_NAME;
}

/** Logo for the given surface; "dark" = shown on dark backgrounds. */
export function getLogoUrl(variant: "light" | "dark" = "light"): string {
  const light = readEnv("NEXT_PUBLIC_LOGO_URL");
  if (variant === "dark") {
    return readEnv("NEXT_PUBLIC_LOGO_DARK_URL") || light || DEFAULT_LOGO_DARK;
  }
  return light || DEFAULT_LOGO_LIGHT;
}

/** Raw configured accent, or undefined on a stock build — the signal
 * BrandStyle uses to skip CSS injection entirely. */
export function getBrandAccentOverride(): string | undefined {
  return readEnv("NEXT_PUBLIC_BRAND_ACCENT_COLOR");
}

export function getBrandAccent(): string {
  return getBrandAccentOverride() || DEFAULT_ACCENT;
}

export function getFaviconUrl(): string {
  return readEnv("NEXT_PUBLIC_FAVICON_URL") || DEFAULT_FAVICON;
}

/** Per-site sidebar logo height (white-label logos vary in aspect ratio).
 * Undefined (the default and the fallback for unsafe values) keeps the
 * stock Tailwind class on the <img>. */
export function getSidebarLogoHeight(): string | undefined {
  const raw = readEnv("NEXT_PUBLIC_SIDEBAR_LOGO_HEIGHT");
  if (!raw || !SAFE_CSS_LENGTH.test(raw)) return undefined;
  return raw;
}

/** Raw theme preset name; resolution/validation lives in lib/brand-themes. */
export function getBrandTheme(): string | undefined {
  return readEnv("NEXT_PUBLIC_BRAND_THEME");
}

/** Solid background color for the login/register pages, sanitized. */
export function getAuthBgColor(): string | undefined {
  const raw = readEnv("NEXT_PUBLIC_BRAND_AUTH_BG_COLOR");
  if (!raw || !SAFE_CSS_COLOR.test(raw)) return undefined;
  return raw;
}

/** Background image URL for the login/register pages, sanitized. */
export function getAuthBgUrl(): string | undefined {
  const raw = readEnv("NEXT_PUBLIC_BRAND_AUTH_BG_URL");
  if (!raw || !SAFE_BG_URL.test(raw)) return undefined;
  return raw;
}
