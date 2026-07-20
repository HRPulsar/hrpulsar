// @vitest-environment jsdom
// HRP-393: white-label brand getters — stock defaults and runtime overrides.
import { afterEach, describe, expect, it } from "vitest";

import {
  DEFAULT_BRAND_NAME,
  getBrandAccent,
  getBrandName,
  getFaviconUrl,
  getLogoUrl,
} from "@/lib/brand";

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
