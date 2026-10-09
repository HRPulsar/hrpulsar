// @vitest-environment jsdom
// HRP-622: a plain employee keeps the company overview only - no Profile,
// Positions or Specializations tab, and a direct link bounces with the
// permission toast. HRP-631: AI-drafting positions and its drafts banner are
// an admin-level role's, never a division head's. HRP-828: the hint into the
// dictionaries shows only to who may open them.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

let roles: string[] = [];
let sections: Record<string, string> = {};
let pathname = "/company";
const replace = vi.fn();
const toastError = vi.fn();

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user: { id: "u-1", roles, sections }, loading: false }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => pathname,
}));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: toastError }),
}));

const { CompanyTabs } = await import("@/components/company/company-tabs");
const { default: CompanyLayout } = await import("@/app/(dashboard)/company/layout");
const { usePermissions } = await import("@/hooks/use-permissions");

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  replace.mockClear();
  toastError.mockClear();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render(node: React.ReactNode, path: string, r: string[], s: Record<string, string>) {
  pathname = path;
  roles = r;
  sections = s;
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        {node}
      </NextIntlClientProvider>,
    );
  });
}

const tabIds = () =>
  [...container.querySelectorAll("[data-testid^='company-tab-']")].map((el) =>
    el.getAttribute("data-testid"),
  );

const ALL_TABS = [
  "company-tab-overview",
  "company-tab-profile",
  "company-tab-positions",
  "company-tab-specializations",
];

describe("company tabs (HRP-622)", () => {
  it("leave a plain employee the overview only", async () => {
    await render(<CompanyTabs />, "/company", ["employee"], { company: "view" });
    expect(tabIds()).toEqual(["company-tab-overview"]);
  });

  it("come back when the tenant raises the employee role to manage", async () => {
    await render(<CompanyTabs />, "/company", ["employee"], { company: "manage" });
    expect(tabIds()).toEqual(ALL_TABS);
  });

  it.each([["hr"], ["manager"], ["recruiter"], ["hiring_manager"], ["admin"]])(
    "stay whole for %s at view",
    async (code) => {
      await render(<CompanyTabs />, "/company", ["employee", code], { company: "view" });
      expect(tabIds()).toEqual(ALL_TABS);
    },
  );
});

describe("company direct links (HRP-622)", () => {
  const page = <div data-testid="page">page</div>;

  it.each([
    ["/company/profile"],
    ["/company/positions"],
    ["/company/positions/p-1"],
    ["/company/specializations"],
    ["/company/specializations/s-1/matrix"],
  ])("bounce a plain employee off %s", async (path) => {
    await render(<CompanyLayout>{page}</CompanyLayout>, path, ["employee"], { company: "view" });
    expect(container.querySelector('[data-testid="page"]')).toBeNull();
    expect(toastError).toHaveBeenCalledWith(enMessages.common.noPermissionPage, expect.anything());
    expect(replace).toHaveBeenCalledWith("/dashboard");
  });

  it.each([["/company"], ["/company/divisions/d-1"]])(
    "keep the overview and divisions open to a plain employee: %s",
    async (path) => {
      await render(<CompanyLayout>{page}</CompanyLayout>, path, ["employee"], { company: "view" });
      expect(container.querySelector('[data-testid="page"]')).not.toBeNull();
      expect(replace).not.toHaveBeenCalled();
    },
  );

  it("open for a manager", async () => {
    await render(<CompanyLayout>{page}</CompanyLayout>, "/company/positions", ["employee", "manager"], {
      company: "manage",
    });
    expect(container.querySelector('[data-testid="page"]')).not.toBeNull();
    expect(replace).not.toHaveBeenCalled();
  });
});

describe("AI-drafted positions (HRP-631)", () => {
  function Probe() {
    return <span data-testid="gen">{String(usePermissions().canGeneratePositions)}</span>;
  }

  it.each([
    [["employee", "manager"], "manage", false],
    [["employee", "recruiter"], "manage", false],
    [["employee", "hr"], "view", false],
    [["employee", "hr"], "manage", true],
    [["employee", "admin"], "manage", true],
  ])("roles %j at %s may generate: %s", async (r, level, expected) => {
    await render(<Probe />, "/company/positions", r, { company: level });
    expect(container.querySelector('[data-testid="gen"]')?.textContent).toBe(String(expected));
  });

  const positionsPage = readFileSync(
    resolve(__dirname, "../app/(dashboard)/company/positions/page.tsx"),
    "utf8",
  );

  it("hides the AI Generate button and the drafts banner below the admin level", () => {
    expect(positionsPage).toMatch(
      /\{canGeneratePositions && \(\s*<Button\s+data-testid="positions-btn-ai-generate"/,
    );
    expect(positionsPage).toContain("{isAdminLevel && drafts.length > 0 && (");
  });
});

describe("the dictionaries hint (HRP-828)", () => {
  const specList = readFileSync(
    resolve(__dirname, "../app/(dashboard)/company/specializations/page.tsx"),
    "utf8",
  );

  it("shows only with manage on the dictionaries", () => {
    expect(specList).toContain('const canDelete = canManageSection("dictionaries");');
    expect(specList).toMatch(
      /\{canDelete && \(\s*<p className="text-xs text-muted-foreground">\s*\{t\("specializationsDictionaryHint"\)\}/,
    );
    // The empty state points there too - a reader gets the plain line.
    expect(specList).toMatch(
      /canDelete\s*\?\s*t\("specializationsEmpty"\)\s*:\s*t\("specializationsEmptyReadOnly"\)/,
    );
  });
});
