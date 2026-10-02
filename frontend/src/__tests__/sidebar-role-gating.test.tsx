// @vitest-environment jsdom
//
// HRP-622 — the sidebar used to render every section for everyone, so a
// rank-and-file employee saw Recruitment and Talent market and landed on
// a 403 (recruitment reads went role-gated in HRP-615). Since HRP-830 the
// Recruitment entry follows /auth/me like every translated section, which
// is what these cases pin.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import { SECTION_CODES } from "@/lib/sections";

// HRP-820: /auth/me lists every open section; a role flag stays on top
// only where a section asks for one (dictionaries, HRP-827). Coverage
// stays dynamic, so it is left out of the default.
const OPEN_ALL: Record<string, string> = Object.fromEntries(
  SECTION_CODES.filter((c) => c !== "coverage").map((c) => [c, "view"]),
);

let roles: string[] = [];
let sections: Record<string, string> = {};
// HRP-820 regression: an enterprise nav item is not a SECTION_CODES member,
// so the matrix must never be the thing that hides it - only its own role
// flag may. Mutable so one test can inject an item without touching the rest.
let eeNavItems: {
  name: string;
  href: string;
  icon: React.ReactNode;
  requireAdmin?: boolean;
  requireManage?: boolean;
}[] = [];

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
}));

vi.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme: "light" }),
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    user: {
      id: "u-1",
      first_name: "Test",
      last_name: "User",
      roles,
      sections,
    },
    tenants: [],
  }),
}));

vi.mock("@/lib/ee-hooks", () => ({
  useEENavItems: () => ({ items: eeNavItems, credits: null }),
}));

vi.mock("@/components/tenant-switcher", () => ({
  SidebarTenantSwitcher: () => null,
}));

vi.mock("@/components/app-version", () => ({
  AppVersion: () => null,
}));

const { Sidebar } = await import("@/components/sidebar");

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  eeNavItems = [];
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function renderAs(
  userRoles: string[],
  userSections: Record<string, string> = OPEN_ALL,
) {
  roles = userRoles;
  sections = userSections;
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <Sidebar />
      </NextIntlClientProvider>,
    );
  });
}

// Scoped to the nav region: the header also carries a `/dashboard` link (the
// logo), which is not a navigation entry and would double-count it (HRP-820).
const hrefs = () =>
  [
    ...container
      .querySelector('[data-testid="sidebar-nav"]')!
      .querySelectorAll("a"),
  ].map((a) => a.getAttribute("href"));

describe("sidebar role gating (HRP-622)", () => {
  it("hides recruitment from a rank-and-file employee", async () => {
    // HRP-830: the matrix hides it - `employee` defaults to `none` there,
    // so /auth/me leaves the section out.
    await renderAs(["employee"], { ...OPEN_ALL, recruitment: "" });
    expect(hrefs()).not.toContain("/recruitment");
    // The everyday surfaces stay.
    expect(hrefs()).toContain("/dashboard");
    expect(hrefs()).toContain("/employees");
    expect(hrefs()).toContain("/company");
    expect(hrefs()).toContain("/assessments");
  });

  it("shows recruitment to a recruiter, who is neither admin nor manager", async () => {
    // ...and not the invitations the default matrix closes to them (the
    // admin block follows the matrix since HRP-831, the talent market
    // since HRP-824 - see the cases at the bottom).
    await renderAs(["recruiter"], { ...OPEN_ALL, invitations: "" });
    expect(hrefs()).toContain("/recruitment");
    expect(hrefs()).not.toContain("/settings/invitations");
  });

  it("shows recruitment to every role /auth/me opens it for", async () => {
    // The five roles the default matrix opens it to, and platform_admin.
    for (const code of [
      "admin",
      "platform_admin",
      "hr",
      "recruiter",
      "hiring_manager",
      "manager",
    ]) {
      await renderAs([code]);
      expect(hrefs(), `role ${code} lost the recruitment entry`).toContain(
        "/recruitment",
      );
    }
  });

  // HRP-810: /auth/me decides - the managers get "manage", anyone who reads
  // at least one process gets "view", everyone else no entry at all.
  it("shows coverage when /auth/me opens the section", async () => {
    await renderAs(["manager"]);
    expect(hrefs(), "a role alone must not open coverage").not.toContain("/coverage");
    await renderAs(["employee"], { ...OPEN_ALL, coverage: "view" });
    expect(hrefs(), "a reader of one process lost the entry").toContain("/coverage");
    await renderAs(["hr"], { ...OPEN_ALL, coverage: "manage" });
    expect(hrefs(), "the section's manager lost the entry").toContain("/coverage");
  });

  it("shows everything to an admin", async () => {
    await renderAs(["admin"], { ...OPEN_ALL, coverage: "manage" });
    expect(hrefs()).toContain("/recruitment");
    expect(hrefs()).toContain("/talent-market");
    expect(hrefs()).toContain("/coverage");
    expect(hrefs()).toContain("/settings/invitations");
  });
});

describe("section access (HRP-820)", () => {
  it("hides an entry the matrix closed, even for an admin", async () => {
    const withoutExams = Object.fromEntries(
      Object.entries(OPEN_ALL).filter(([code]) => code !== "exams"),
    );
    await renderAs(["admin"], { ...withoutExams, coverage: "manage" });
    expect(hrefs()).not.toContain("/exams");
    expect(hrefs()).toContain("/employees");
  });

  // HRP-820 regression: the sidebar filter used to be a blacklist
  // (`id !== "dashboard" && id !== "billing"`) coupled to the `eeAsNav` id
  // hack, so any future enterprise entry other than billing would get
  // `id === ""`, `canViewSection("")` → false, and silently vanish for
  // everyone including admin. The fix is an allowlist: only ids that are
  // SECTION_CODES members go through the matrix at all. Billing is the one
  // enterprise id this repo can render today (see eeAsNav in sidebar.tsx),
  // so it is the observable proof the allowlist leaves non-matrix ids to
  // their own role flag.
  it("leaves the billing entry to its own role flag, not the matrix", async () => {
    eeNavItems = [{ name: "Billing", href: "/settings/billing", icon: null, requireAdmin: true }];
    await renderAs(["admin"], OPEN_ALL);
    expect(hrefs()).toContain("/settings/billing");
    await renderAs(["employee"], OPEN_ALL);
    expect(hrefs()).not.toContain("/settings/billing");
  });

  // HRP-822: analytics is translated, so its role flag
  // (`requireManagementData`) is gone and the matrix is the only gate left
  // on the entry - which is what lets an admin hand the section to a role
  // that never had it.
  it("opens analytics to whoever the matrix opened it to", async () => {
    const withoutAnalytics = Object.fromEntries(
      Object.entries(OPEN_ALL).filter(([code]) => code !== "analytics"),
    );
    await renderAs(["employee"], withoutAnalytics);
    expect(hrefs()).not.toContain("/analytics");
    await renderAs(["employee"], { ...withoutAnalytics, analytics: "view" });
    expect(hrefs()).toContain("/analytics");
  });

  it("opens the admin block to whoever the matrix opened it to (HRP-831)", async () => {
    // Until HRP-831 the four entries kept an admin flag on top of the
    // matrix; now the row alone decides. Dictionaries still asks for
    // `manage` (its `view` is the pickers), so `view` there hides it.
    await renderAs(["hr"], OPEN_ALL);
    expect(hrefs()).not.toContain("/dictionaries");
    for (const href of ["/settings/invitations", "/settings/import", "/settings/roles", "/settings/ai"]) {
      expect(hrefs()).toContain(href);
    }
    await renderAs(["admin"], { ...OPEN_ALL, invitations: "" });
    expect(hrefs()).not.toContain("/settings/invitations");
  });

  it("keeps the dashboard whatever the matrix says", async () => {
    await renderAs(["employee"], {});
    expect(hrefs()).toEqual(["/dashboard"]);
  });
});

// HRP-765 opened the talent market entry to the employee whose name is on
// a card, on top of admin / manager, with a role flag of its own. HRP-824
// translated the section: the entry follows the tenant's matrix alone -
// the employee's `view` is a row in it, and so is a role the tenant closed
// it for - and the flag is gone.
describe("talent market entry (HRP-765, HRP-824)", () => {
  it("is there for a rank-and-file employee the matrix opens it to", async () => {
    await renderAs(["employee"]);
    expect(hrefs()).toContain("/talent-market");
  });

  it("is there for every role the matrix opens it to, the ones the old flag kept out included", async () => {
    for (const code of ["admin", "manager", "hr", "recruiter", "hiring_manager"]) {
      await renderAs([code]);
      expect(hrefs(), `role ${code} lost the talent market entry`).toContain(
        "/talent-market",
      );
    }
  });

  it("is gone for a role the matrix closed it for, whatever the role", async () => {
    const closed = Object.fromEntries(
      Object.entries(OPEN_ALL).filter(([code]) => code !== "talent-market"),
    );
    for (const code of ["employee", "manager", "admin"]) {
      await renderAs([code], closed);
      expect(hrefs(), `role ${code} kept a closed talent market`).not.toContain(
        "/talent-market",
      );
    }
  });
});
