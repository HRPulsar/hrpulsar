// @vitest-environment jsdom
//
// HRP-1045: the Recruitment → Settings tabs open to the audiences their
// APIs already admit - the scales to `manage` on recruitment, retention
// and roles to the admin | hr role (read-only below admin), branding and
// consent templates read at `manage` with writes kept for admin, the
// LLM / transcription providers to admin alone. Only reachable tiles show.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

let user: {
  id: string;
  roles: string[];
  sections: Record<string, string>;
} | null = null;

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user, loading: false }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/recruitment/settings",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    get: vi.fn((url: string) => {
      if (url === "/recruitment/settings/retention")
        return Promise.resolve({
          interviews_days: 365,
          resumes_days: 365,
          consents_days: 365,
          reports_days: 365,
        });
      if (url === "/recruitment/settings/branding")
        return Promise.resolve({
          logo_file_id: null,
          logo_url: null,
          accent_color: "#0066ff",
          secondary_color: null,
          watermark_text: null,
          raw: null,
        });
      if (url === "/recruitment/consent-templates")
        return Promise.resolve([
          {
            id: "tpl-1",
            name: "Default",
            body: "Consent body",
            language: "en",
            is_active: false,
            version: 1,
          },
        ]);
      return Promise.reject(new Error(`not mocked: ${url}`));
    }),
    post: vi.fn(() => Promise.resolve({})),
    put: vi.fn(() => Promise.resolve({})),
  },
}));

const { default: SettingsHubPage } = await import(
  "@/app/(dashboard)/recruitment/settings/page"
);
const { default: RetentionPage } = await import(
  "@/app/(dashboard)/recruitment/settings/retention/page"
);
const { default: BrandingPage } = await import(
  "@/app/(dashboard)/recruitment/settings/branding/page"
);
const { default: ConsentTemplatesPage } = await import(
  "@/app/(dashboard)/recruitment/settings/consent-templates/page"
);

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
});

async function render(
  node: React.ReactNode,
  roles: string[],
  recruitment: string,
) {
  user = { id: "u-1", roles, sections: { recruitment } };
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        {node}
      </NextIntlClientProvider>,
    );
  });
  for (let i = 0; i < 4; i++) {
    await act(async () => {
      await Promise.resolve();
    });
  }
}

const byId = (id: string) => container.querySelector(`[data-testid="${id}"]`);

const ALL_TILES = [
  "scales",
  "llm",
  "stt",
  "branding",
  "retention",
  "roles",
  "consent-templates",
  "gdpr",
  "audit",
];

async function visibleTiles(roles: string[], recruitment: string) {
  await render(<SettingsHubPage />, roles, recruitment);
  return ALL_TILES.filter((t) => byId(`rec-settings-card-${t}`) !== null);
}

describe("Recruitment settings follow the APIs' audiences (HRP-1045)", () => {
  it("shows the admin every tile", async () => {
    expect(await visibleTiles(["admin"], "manage")).toEqual(ALL_TILES);
  });

  it("shows a recruiter at manage the scales, branding and consents only", async () => {
    expect(await visibleTiles(["recruiter"], "manage")).toEqual([
      "scales",
      "branding",
      "consent-templates",
    ]);
  });

  it("adds retention, roles, gdpr and audit for hr", async () => {
    expect(await visibleTiles(["hr"], "manage")).toEqual([
      "scales",
      "branding",
      "retention",
      "roles",
      "consent-templates",
      "gdpr",
      "audit",
    ]);
  });

  // HRP-1045 REDO (QA 14.10): one subtitle for everyone; the GDPR pointer
  // only where GDPR opens (admin, hr) - the rest read the funnel note.
  it("words the hub by audience", async () => {
    const m = enMessages.recruitment;
    for (const [roles, gdpr] of [
      [["admin"], true],
      [["hr"], true],
      [["recruiter"], false],
      [["manager"], false],
      [["hiring_manager"], false],
    ] as const) {
      await render(<SettingsHubPage />, [...roles], "manage");
      const text = byId("recruitment-settings-hub")!.textContent!;
      expect(text).toContain(m.settingsDescription);
      expect(text).toContain(gdpr ? m.settingsWhatElseBody : m.settingsWhatElseBodyFunnel);
      if (!gdpr) expect(text, roles[0]).not.toContain("GDPR");
    }
  });

  it("lets hr read retention without the save button", async () => {
    await render(<RetentionPage />, ["hr"], "manage");
    expect(byId("retention-input-interviews_days")).not.toBeNull();
    expect(
      (byId("retention-input-interviews_days") as HTMLInputElement).disabled,
    ).toBe(true);
    expect(byId("retention-btn-save")).toBeNull();
  });

  it("keeps the retention save for the admin", async () => {
    await render(<RetentionPage />, ["admin"], "manage");
    expect(
      (byId("retention-input-interviews_days") as HTMLInputElement).disabled,
    ).toBe(false);
    expect(byId("retention-btn-save")).not.toBeNull();
  });

  it("lets a recruiter read branding without the save button", async () => {
    await render(<BrandingPage />, ["recruiter"], "manage");
    expect(byId("brand-input-watermark")).not.toBeNull();
    expect((byId("brand-input-watermark") as HTMLInputElement).disabled).toBe(
      true,
    );
    expect(byId("brand-btn-save")).toBeNull();
  });

  it("lets a recruiter read consent templates without the writes", async () => {
    await render(<ConsentTemplatesPage />, ["recruiter"], "manage");
    expect(byId("consent-tpl-row-tpl-1")).not.toBeNull();
    expect(byId("consent-tpl-btn-create")).toBeNull();
    expect(byId("consent-tpl-btn-save-tpl-1")).toBeNull();
    expect(byId("consent-tpl-btn-activate-tpl-1")).toBeNull();
  });

  it("keeps the consent template writes for the admin", async () => {
    await render(<ConsentTemplatesPage />, ["admin"], "manage");
    expect(byId("consent-tpl-btn-create")).not.toBeNull();
    expect(byId("consent-tpl-btn-save-tpl-1")).not.toBeNull();
    expect(byId("consent-tpl-btn-activate-tpl-1")).not.toBeNull();
  });
});
