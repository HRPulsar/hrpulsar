// @vitest-environment jsdom
//
// HRP-808 — per-tenant theme preset / accent on top of the site's env
// branding. buildBrandCss is shared by the server BrandStyle (site env) and
// the client TenantBrandStyle (tenant settings from /auth/me).

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BRAND_THEMES, buildBrandCss } from "@/lib/brand-themes";
import type { User } from "@/lib/types";

let user: Partial<User> | null = null;

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user }),
}));

const { TenantBrandStyle } = await import("@/components/tenant-brand-style");

const blocks = (css: string) => {
  const m = css.match(/^:root:root \{(.*)\}\.dark:root:root \{(.*)\}$/);
  if (!m) throw new Error(`unexpected css shape: ${css}`);
  return { light: m[1], dark: m[2] };
};

describe("buildBrandCss", () => {
  it("returns null with nothing to override", () => {
    expect(buildBrandCss(undefined, undefined)).toBeNull();
  });

  it("accent alone recolors the accent in both modes", () => {
    const { light, dark } = blocks(buildBrandCss(undefined, "#112233")!);
    for (const block of [light, dark]) {
      expect(block).toContain("--brand-accent: #112233;");
      expect(block).toContain("--accent: #112233;");
      expect(block).toContain(
        "--brand-accent-hover: color-mix(in oklab, #112233 85%, black);",
      );
      expect(block).not.toContain("--background");
    }
  });

  it("a preset emits its light and dark tokens", () => {
    const { light, dark } = blocks(buildBrandCss(BRAND_THEMES.teal, undefined)!);
    expect(light).toContain(`--background: ${BRAND_THEMES.teal.light["--background"]};`);
    expect(dark).toContain(`--background: ${BRAND_THEMES.teal.dark["--background"]};`);
    expect(light).toContain(`--radius: ${BRAND_THEMES.teal.light["--radius"]};`);
  });

  it("an accent lands on top of the preset in both modes", () => {
    const { light, dark } = blocks(buildBrandCss(BRAND_THEMES.violet, "#00AA00")!);
    expect(light).toContain("--accent: #00AA00;");
    expect(dark).toContain("--accent: #00AA00;");
    expect(light).not.toContain(`--accent: ${BRAND_THEMES.violet.light["--accent"]};`);
  });

  it("drops an accent that could escape the declaration", () => {
    expect(buildBrandCss(undefined, "red;}body{display:none")).toBeNull();
  });
});

describe("BrandStyle (site env)", () => {
  afterEach(() => {
    delete window.__ENV__;
  });

  // Pinned literally, not via buildBrandCss: every white-label site renders
  // this, and a helper change must not pass by comparing against itself.
  const ACCENT_VARS =
    "--brand-accent: #123456;" +
    "--brand-accent-hover: color-mix(in oklab, #123456 85%, black);" +
    "--brand-accent-deep: color-mix(in oklab, #123456 60%, black);" +
    "--accent: #123456;--ring: #123456;--sidebar-primary: #123456;" +
    "--sidebar-ring: #123456;--chart-1: #123456;";

  it("recolors the accent in both modes from the site env", async () => {
    window.__ENV__ = { NEXT_PUBLIC_BRAND_ACCENT_COLOR: "#123456" };
    const { BrandStyle } = await import("@/components/brand-style");
    expect(BrandStyle()?.props.children).toBe(
      `:root:root {${ACCENT_VARS}}.dark:root:root {${ACCENT_VARS}}`,
    );
  });

  it("layers the site accent over the site preset", async () => {
    window.__ENV__ = {
      NEXT_PUBLIC_BRAND_THEME: "teal",
      NEXT_PUBLIC_BRAND_ACCENT_COLOR: "#123456",
    };
    const { BrandStyle } = await import("@/components/brand-style");
    const { light, dark } = blocks(BrandStyle()?.props.children);
    expect(light.startsWith(`--background: ${BRAND_THEMES.teal.light["--background"]};`)).toBe(true);
    expect(dark.startsWith(`--background: ${BRAND_THEMES.teal.dark["--background"]};`)).toBe(true);
    for (const block of [light, dark]) {
      expect(block).toContain("--accent: #123456;");
      expect(block).toContain("--brand-accent-deep: color-mix(in oklab, #123456 60%, black);");
      expect(block).toContain("--radius: ");
    }
  });

  it("renders nothing on a stock build", async () => {
    const { BrandStyle } = await import("@/components/brand-style");
    expect(BrandStyle()).toBeNull();
  });
});

describe("TenantBrandStyle", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    user = null;
  });

  async function renderWith(u: Partial<User> | null) {
    user = u;
    await act(async () => root.render(<TenantBrandStyle />));
    return container.querySelector("style");
  }

  it("renders nothing when the tenant inherits the site", async () => {
    expect(await renderWith({ tenant_brand_theme: null, tenant_brand_accent_color: null })).toBeNull();
    expect(await renderWith(null)).toBeNull();
  });

  it("renders the tenant preset and accent", async () => {
    const style = await renderWith({
      tenant_brand_theme: "slate",
      tenant_brand_accent_color: "#ABCDEF",
    });
    expect(style?.textContent).toBe(buildBrandCss(BRAND_THEMES.slate, "#ABCDEF"));
  });

  it("accepts only a #RRGGBB tenant accent", async () => {
    expect(
      await renderWith({ tenant_brand_theme: null, tenant_brand_accent_color: "url(//evil/x)" }),
    ).toBeNull();
  });

  it("ignores an unknown preset name but keeps the accent", async () => {
    const style = await renderWith({
      tenant_brand_theme: "neon",
      tenant_brand_accent_color: "#ABCDEF",
    });
    expect(style?.textContent).toBe(buildBrandCss(undefined, "#ABCDEF"));
  });
});
