// @vitest-environment jsdom
//
// HRP-808 — the accent swatch in the platform tenant branding card shows
// the accent the tenant actually sees while it has none of its own (the
// tenant preset, else the site env branding), and a refused save puts the
// saved accent back instead of leaving the unsaved pick on screen.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { PlatformTenantDetail } from "@/lib/types";

const TEAL_ACCENT = "oklch(0.6 0.115 195)";
const VIOLET_ACCENT = "oklch(0.54 0.22 293)";
// jsdom has no canvas: a stand-in that "parses" the two preset accents.
const RGB: Record<string, number[]> = {
  [TEAL_ACCENT]: [0, 150, 160],
  [VIOLET_ACCENT]: [120, 60, 230],
};

const getTenant = vi.fn();
const updateTenant = vi.fn();

vi.mock("@/lib/api-platform", () => ({
  platformApi: { getTenant, updateTenant },
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "t-1" }),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { default: TenantDetailPage } = await import(
  "@/app/(platform)/platform/tenants/[id]/page"
);

const TENANT: PlatformTenantDetail = {
  id: "t-1",
  name: "Acme Works",
  slug: "acme",
  billing_status: "active",
  is_active: true,
  users_count: 1,
  employees_count: 1,
  created_at: "2026-01-01T00:00:00Z",
  industry: null,
  company_size: null,
  website: null,
  description: null,
  free_credits: 0,
  paid_credits: 0,
  total_credits: 0,
  credits_reset_day: 1,
  credit_warning_threshold: 0,
  last_activity: null,
  admin_email: null,
  hide_platform_logo: false,
  hide_app_version: false,
  brand_theme: null,
  brand_accent_color: null,
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => {
    let fill = "#000000";
    return {
      get fillStyle() {
        return fill;
      },
      set fillStyle(value: string) {
        if (value.startsWith("#") || value in RGB) fill = value;
      },
      fillRect: () => {},
      getImageData: () => ({ data: [...(RGB[fill] ?? [0, 0, 0]), 255] }),
    } as never;
  });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  delete window.__ENV__;
  vi.restoreAllMocks();
});

async function renderTenant(branding: Partial<PlatformTenantDetail>) {
  getTenant.mockResolvedValue({ ...TENANT, ...branding });
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <TenantDetailPage />
      </NextIntlClientProvider>,
    );
  });
  return container.querySelector(
    '[data-testid="platform-tenant-branding-input-accent"]',
  ) as HTMLInputElement;
}

describe("tenant branding card accent (HRP-808)", () => {
  it("inherits the site preset's accent", async () => {
    window.__ENV__ = { NEXT_PUBLIC_BRAND_THEME: "teal" };
    const input = await renderTenant({});
    expect(input.value).toBe("#0096a0");
  });

  it("inherits the tenant's own preset over the site's", async () => {
    window.__ENV__ = { NEXT_PUBLIC_BRAND_THEME: "teal" };
    const input = await renderTenant({ brand_theme: "violet" });
    expect(input.value).toBe("#783ce6");
  });

  it("puts the saved accent back when the save is refused", async () => {
    updateTenant.mockRejectedValue(new Error("nope"));
    const input = await renderTenant({ brand_accent_color: "#112233" });

    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!;
      setValue.call(input, "#445566");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(input.value).toBe("#445566");

    await act(async () => {
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(updateTenant).toHaveBeenCalledWith("t-1", {
      brand_accent_color: "#445566",
    });
    expect(input.value).toBe("#112233");
  });
});
