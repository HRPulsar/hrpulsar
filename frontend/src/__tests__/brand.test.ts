// @vitest-environment jsdom
// HRP-393: white-label brand getters — stock defaults and runtime overrides.
import { afterEach, describe, expect, it } from "vitest";

import {
  DEFAULT_BRAND_NAME,
  getAuthBgColor,
  getAuthBgUrl,
  getBrandAccent,
  getBrandName,
  getBrandTheme,
  getFaviconUrl,
  getLogoUrl,
  getSidebarLogoHeight,
} from "@/lib/brand";
import {
  BRAND_THEMES,
  REQUIRED_THEME_TOKENS,
  resolveThemePreset,
} from "@/lib/brand-themes";

type Env = NonNullable<Window["__ENV__"]>;

function setEnv(env: Env) {
  window.__ENV__ = env;
}

afterEach(() => {
  delete window.__ENV__;
  delete process.env.NEXT_PUBLIC_BRAND_NAME;
  delete process.env.NEXT_PUBLIC_LOGO_URL;
  delete process.env.NEXT_PUBLIC_LOGO_DARK_URL;
  delete process.env.NEXT_PUBLIC_BRAND_ACCENT_COLOR;
  delete process.env.NEXT_PUBLIC_FAVICON_URL;
  delete process.env.NEXT_PUBLIC_SIDEBAR_LOGO_HEIGHT;
  delete process.env.NEXT_PUBLIC_BRAND_THEME;
  delete process.env.NEXT_PUBLIC_BRAND_AUTH_BG_COLOR;
  delete process.env.NEXT_PUBLIC_BRAND_AUTH_BG_URL;
});

describe("stock defaults", () => {
  it("returns the HRPulsar brand with no overrides", () => {
    expect(getBrandName()).toBe(DEFAULT_BRAND_NAME);
    expect(getLogoUrl("light")).toBe("/brand/logo-horizontal-color-light.svg");
    expect(getLogoUrl("dark")).toBe("/brand/logo-horizontal-color.svg");
    expect(getBrandAccent()).toBe("#0066FF");
    expect(getFaviconUrl()).toBe("/icon.svg");
  });
});

describe("runtime overrides via window.__ENV__", () => {
  it("prefers window.__ENV__ values", () => {
    setEnv({
      NEXT_PUBLIC_BRAND_NAME: "Acme Talent",
      NEXT_PUBLIC_LOGO_URL: "/custom/logo.svg",
      NEXT_PUBLIC_LOGO_DARK_URL: "/custom/logo-dark.svg",
      NEXT_PUBLIC_BRAND_ACCENT_COLOR: "#AA0044",
      NEXT_PUBLIC_FAVICON_URL: "/custom/favicon.png",
    });
    expect(getBrandName()).toBe("Acme Talent");
    expect(getLogoUrl("light")).toBe("/custom/logo.svg");
    expect(getLogoUrl("dark")).toBe("/custom/logo-dark.svg");
    expect(getBrandAccent()).toBe("#AA0044");
    expect(getFaviconUrl()).toBe("/custom/favicon.png");
  });

  it("falls back dark logo to the light override when only LOGO_URL is set", () => {
    setEnv({ NEXT_PUBLIC_LOGO_URL: "/custom/logo.svg" });
    expect(getLogoUrl("dark")).toBe("/custom/logo.svg");
    expect(getLogoUrl("light")).toBe("/custom/logo.svg");
  });

  it("window.__ENV__ wins over process.env", () => {
    process.env.NEXT_PUBLIC_BRAND_NAME = "FromProcess";
    setEnv({ NEXT_PUBLIC_BRAND_NAME: "FromWindow" });
    expect(getBrandName()).toBe("FromWindow");
  });
});

describe("process.env fallback", () => {
  it("reads process.env when window.__ENV__ is absent", () => {
    process.env.NEXT_PUBLIC_BRAND_NAME = "EnvBrand";
    process.env.NEXT_PUBLIC_BRAND_ACCENT_COLOR = "#123456";
    expect(getBrandName()).toBe("EnvBrand");
    expect(getBrandAccent()).toBe("#123456");
  });
});

// HRP-463: sidebar logo height override.
describe("getSidebarLogoHeight", () => {
  it("defaults to undefined (stock h-7 class applies)", () => {
    expect(getSidebarLogoHeight()).toBeUndefined();
  });

  it("accepts px and rem lengths", () => {
    setEnv({ NEXT_PUBLIC_SIDEBAR_LOGO_HEIGHT: "28px" });
    expect(getSidebarLogoHeight()).toBe("28px");
    setEnv({ NEXT_PUBLIC_SIDEBAR_LOGO_HEIGHT: "1.75rem" });
    expect(getSidebarLogoHeight()).toBe("1.75rem");
  });

  it("rejects anything that is not a plain px/rem length", () => {
    for (const bad of ["28", "28vh", "28px; color: red", "calc(2rem)", "-8px"]) {
      setEnv({ NEXT_PUBLIC_SIDEBAR_LOGO_HEIGHT: bad });
      expect(getSidebarLogoHeight()).toBeUndefined();
    }
  });
});

// HRP-463: theme presets.
describe("brand themes", () => {
  it("getBrandTheme returns the raw env value or undefined", () => {
    expect(getBrandTheme()).toBeUndefined();
    setEnv({ NEXT_PUBLIC_BRAND_THEME: "teal" });
    expect(getBrandTheme()).toBe("teal");
  });

  it("resolves known presets and falls back to stock otherwise", () => {
    expect(resolveThemePreset("teal")).toBe(BRAND_THEMES.teal);
    expect(resolveThemePreset("slate")).toBe(BRAND_THEMES.slate);
    expect(resolveThemePreset(undefined)).toBeUndefined();
    expect(resolveThemePreset("")).toBeUndefined();
    expect(resolveThemePreset("default")).toBeUndefined();
    expect(resolveThemePreset("no-such-theme")).toBeUndefined();
  });

  it("every preset declares the full required token set in both modes", () => {
    for (const [name, preset] of Object.entries(BRAND_THEMES)) {
      for (const token of REQUIRED_THEME_TOKENS) {
        expect(preset.light[token], `${name}.light ${token}`).toBeTruthy();
        expect(preset.dark[token], `${name}.dark ${token}`).toBeTruthy();
      }
    }
  });

  it("presets carry no unexpected tokens (no typos outside the contract)", () => {
    const allowed = new Set<string>(REQUIRED_THEME_TOKENS);
    for (const [name, preset] of Object.entries(BRAND_THEMES)) {
      for (const mode of ["light", "dark"] as const) {
        for (const token of Object.keys(preset[mode])) {
          expect(allowed.has(token), `${name}.${mode} ${token}`).toBe(true);
        }
      }
    }
  });
});

// HRP-463: auth page background overrides.
describe("auth background", () => {
  it("defaults to undefined (stock starfield)", () => {
    expect(getAuthBgColor()).toBeUndefined();
    expect(getAuthBgUrl()).toBeUndefined();
  });

  it("accepts safe CSS colors", () => {
    setEnv({ NEXT_PUBLIC_BRAND_AUTH_BG_COLOR: "#112233" });
    expect(getAuthBgColor()).toBe("#112233");
    setEnv({ NEXT_PUBLIC_BRAND_AUTH_BG_COLOR: "oklch(0.2 0.03 250)" });
    expect(getAuthBgColor()).toBe("oklch(0.2 0.03 250)");
  });

  it("rejects colors that could escape the declaration", () => {
    for (const bad of ["red;}", "#123};body{", "x{y:z}"]) {
      setEnv({ NEXT_PUBLIC_BRAND_AUTH_BG_COLOR: bad });
      expect(getAuthBgColor()).toBeUndefined();
    }
  });

  it("accepts absolute http(s) and root-relative image URLs", () => {
    setEnv({ NEXT_PUBLIC_BRAND_AUTH_BG_URL: "https://cdn.acme.example/bg.jpg" });
    expect(getAuthBgUrl()).toBe("https://cdn.acme.example/bg.jpg");
    setEnv({ NEXT_PUBLIC_BRAND_AUTH_BG_URL: "/brand/auth-bg.jpg" });
    expect(getAuthBgUrl()).toBe("/brand/auth-bg.jpg");
  });

  it("rejects unsafe or non-http URL schemes", () => {
    for (const bad of [
      "javascript:alert(1)",
      "data:image/png;base64,AAAA",
      'https://x/y".jpg',
      "https://x/y) no-repeat",
      "ftp://x/y.jpg",
    ]) {
      setEnv({ NEXT_PUBLIC_BRAND_AUTH_BG_URL: bad });
      expect(getAuthBgUrl()).toBeUndefined();
    }
  });
});
