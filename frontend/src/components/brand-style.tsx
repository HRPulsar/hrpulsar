import { getBrandAccentOverride } from "@/lib/brand";

/**
 * CSS variable overrides for a custom accent color (HRP-393).
 *
 * Renders nothing on a default build, so the stock theme ships untouched.
 * Server component: getBrandAccentOverride() reads the live container env
 * on every SSR pass — the root layout is already dynamic via
 * RuntimeEnvScript's headers() call.
 *
 * The doubled :root:root selector outranks both the `:root` and `.dark`
 * blocks in globals.css regardless of stylesheet order, so one configured
 * accent applies to both themes. Hover/deep shades are derived with
 * color-mix; the stock #0052CC/#003C99 shades stay hardcoded in
 * globals.css for the default build.
 */

// Whitelist of characters valid in a CSS color (hex, rgb()/oklch()/named);
// anything else (braces, semicolons) could escape the declaration block.
const SAFE_CSS_COLOR = /^[#a-zA-Z0-9(),.%\s/-]+$/;

export function BrandStyle() {
  const accent = getBrandAccentOverride();
  if (!accent || !SAFE_CSS_COLOR.test(accent)) return null;
  const css =
    ":root:root {" +
    `--brand-accent: ${accent};` +
    `--brand-accent-hover: color-mix(in oklab, ${accent} 85%, black);` +
    `--brand-accent-deep: color-mix(in oklab, ${accent} 60%, black);` +
    `--accent: ${accent};` +
    `--ring: ${accent};` +
    `--sidebar-primary: ${accent};` +
    `--sidebar-ring: ${accent};` +
    `--chart-1: ${accent};` +
    "}";
  return <style>{css}</style>;
}
