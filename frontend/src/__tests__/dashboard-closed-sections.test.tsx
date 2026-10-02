// @vitest-environment jsdom
//
// HRP-820: the dashboard must not ask for the data of a section the
// tenant's access matrix closed for the caller. Before this, a closed
// `analytics` section was discovered by sending `/analytics/dev-loop`
// and reading its 403 - now `/auth/me` already says whether the section
// is open, so the request itself must not go out. These pin WHICH paths
// `api.get` is called with, not what the page renders with the answer.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

let sections: Record<string, string> = {};
// HRP-820 fix round 1: a real backend outage, not a closed section, is the
// one thing that must still flip the dashboard into its load-error state.
let companyFails = false;
// Review 01.10: `/onboarding/status` is a shared read every role passes
// (HRP-828), so its failure is a real one and must not be swallowed.
let onboardingFails = false;

const getMock = vi.fn((path: string) => {
  if (onboardingFails && path === "/onboarding/status") {
    return Promise.reject(new Error("backend down"));
  }
  if (path === "/onboarding/status") {
    return Promise.resolve({ needs_onboarding: false });
  }
  if (path === "/company") {
    return companyFails
      ? Promise.reject(new Error("backend down"))
      : Promise.resolve({ id: "t-1", name: "Acme" });
  }
  if (path.startsWith("/assessments")) {
    return Promise.resolve({ items: [] });
  }
  // /analytics/dev-loop, /analytics/my-loop: the page already tolerates a
  // failed fetch (null data / no crash), and these tests only care which
  // paths were requested.
  return Promise.reject(new Error("not mocked"));
});

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api: { get: getMock, post: vi.fn() },
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user: { id: "u-1", is_platform_admin: false, sections } }),
}));

// A fresh object on every call would change `router`'s identity each
// render, and the effect's dependency array includes `router` - that
// would retrigger the effect (and its setState calls) forever.
const { routerMock } = vi.hoisted(() => ({ routerMock: { replace: vi.fn() } }));

vi.mock("next/navigation", () => ({
  useRouter: () => routerMock,
}));

const DashboardPage = (await import("@/app/(dashboard)/dashboard/page"))
  .default;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  getMock.mockClear();
  routerMock.replace.mockClear();
  companyFails = false;
  onboardingFails = false;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render() {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <DashboardPage />
      </NextIntlClientProvider>,
    );
  });
}

const paths = () => getMock.mock.calls.map((c) => String(c[0]));

describe("dashboard requests only the sections the matrix opened (HRP-820)", () => {
  it("skips dev-loop and falls to my-loop when analytics is closed", async () => {
    sections = { assessments: "view" };
    await render();
    expect(paths().some((p) => p.startsWith("/analytics/dev-loop"))).toBe(
      false,
    );
    expect(paths()).toContain("/analytics/my-loop");
  });

  it("skips /assessments when the section is closed", async () => {
    sections = { analytics: "view" };
    await render();
    expect(paths().some((p) => p.startsWith("/assessments"))).toBe(false);
  });

  it("requests both when both sections are open", async () => {
    sections = { assessments: "view", analytics: "view" };
    await render();
    expect(paths().some((p) => p.startsWith("/assessments"))).toBe(true);
    expect(paths().some((p) => p.startsWith("/analytics/dev-loop"))).toBe(
      true,
    );
  });
});

describe("a skipped section request is neutral in the load-error rule (HRP-820)", () => {
  it("still renders the load-error state when everything reachable is actually down", async () => {
    // Both sections closed - neither /assessments nor /analytics/dev-loop
    // is requested at all - and the two requests that DO go out both
    // genuinely fail: a real backend outage, not a closed-section skip.
    sections = {};
    companyFails = true;
    await render();
    expect(
      container.querySelector('[data-testid="dashboard-load-failed"]'),
    ).not.toBeNull();
  });

  it("shows the retry state when /onboarding/status fails", async () => {
    // A transient failure used to be swallowed: a new tenant's admin
    // skipped the onboarding redirect and landed on an empty dashboard.
    sections = { assessments: "view" };
    onboardingFails = true;
    await render();
    expect(
      container.querySelector('[data-testid="dashboard-load-failed"]'),
    ).not.toBeNull();
    expect(routerMock.replace).not.toHaveBeenCalledWith("/onboarding");
  });
});
