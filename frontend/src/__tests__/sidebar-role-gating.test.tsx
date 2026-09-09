// @vitest-environment jsdom
//
// HRP-622 — the sidebar used to render every section for everyone, so a
// rank-and-file employee saw Recruitment and Talent market and landed on
// a 403 (recruitment reads went role-gated in HRP-615). The gate on the
// Recruitment entry must stay identical to the backend's
// RECRUITMENT_VIEWER_ROLES, which is what these cases pin.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

let roles: string[] = [];

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
    },
  }),
}));

vi.mock("@/lib/ee-hooks", () => ({
  useEENavItems: () => ({ items: [], credits: null }),
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
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function renderAs(userRoles: string[]) {
  roles = userRoles;
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <Sidebar />
      </NextIntlClientProvider>,
    );
  });
}

const hrefs = () =>
  [...container.querySelectorAll("a")].map((a) => a.getAttribute("href"));

describe("sidebar role gating (HRP-622)", () => {
  it("hides recruitment from a rank-and-file employee", async () => {
    await renderAs(["employee"]);
    expect(hrefs()).not.toContain("/recruitment");
    // The everyday surfaces stay.
    expect(hrefs()).toContain("/dashboard");
    expect(hrefs()).toContain("/employees");
    expect(hrefs()).toContain("/company");
    expect(hrefs()).toContain("/assessments");
  });

  it("shows recruitment to a recruiter, who is neither admin nor manager", async () => {
    await renderAs(["recruiter"]);
    expect(hrefs()).toContain("/recruitment");
    // ...but not the admin-or-manager surfaces.
    expect(hrefs()).not.toContain("/talent-market");
    expect(hrefs()).not.toContain("/settings/invitations");
  });

  it("shows recruitment to every RECRUITMENT_VIEWER_ROLES member", async () => {
    // Same six codes as backend/app/modules/recruitment/routers/common.py.
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

  it("shows everything to an admin", async () => {
    await renderAs(["admin"]);
    expect(hrefs()).toContain("/recruitment");
    expect(hrefs()).toContain("/talent-market");
    expect(hrefs()).toContain("/settings/invitations");
  });
});

// HRP-765 — the talent market entry was admin/manager-only, which shut
// out the one role the board is about: the employee whose name is on a
// card's candidate list. Reading is scoped per role on the API (an
// employee sees the cards they are a candidate on), so the entry is the
// employee's as well — and stays out of the menus of the roles the ticket
// did not name.
describe("talent market entry (HRP-765)", () => {
  it("is there for a rank-and-file employee", async () => {
    await renderAs(["employee"]);
    expect(hrefs()).toContain("/talent-market");
  });

  it("is still there for the roles that manage it", async () => {
    for (const code of ["admin", "manager"]) {
      await renderAs([code]);
      expect(hrefs(), `role ${code} lost the talent market entry`).toContain(
        "/talent-market",
      );
    }
  });

  it("stays out of the menu for the roles the ticket did not name", async () => {
    for (const code of ["hr", "recruiter", "hiring_manager"]) {
      await renderAs([code]);
      expect(hrefs(), `role ${code} gained the talent market entry`).not.toContain(
        "/talent-market",
      );
    }
  });
});
