// @vitest-environment jsdom
//
// The sandbox's start routes (HRP-1159): "Where to start" once, to the
// admin persona only; the strip walks the picked route by page and by the
// demo card's value moments, and goes once the route's create is done.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

const env = vi.hoisted(() => ({
  pathname: "/coverage",
  persona: "admin" as "admin" | "employee",
  anchor: "a1a1a1a1-0000-4000-8000-000000000001" as string | null,
}));

vi.mock("next/navigation", () => ({ usePathname: () => env.pathname }));
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    user: { tenant_id: "t-demo", tenant_is_demo: true, demo_persona: env.persona },
  }),
}));
vi.mock("@/lib/demo", () => ({
  saveDemoAccess: vi.fn(),
  chooseDemoGuide: vi.fn(() => Promise.resolve({ assessment_id: env.anchor })),
}));

import { DemoGuide } from "@/components/dashboard/demo-guide";
import { MUTATION_EVENT, type MutationEventDetail } from "@/lib/api";
import { chooseDemoGuide } from "@/lib/demo";

const PROCESS = "/coverage/c0c0c0c0-0000-4000-8000-000000000002";
const ASSESSMENT = "/assessments/a2a2a2a2-0000-4000-8000-000000000003";

const storage = new Map<string, string>();
vi.stubGlobal("localStorage", {
  getItem: (k: string) => storage.get(k) ?? null,
  setItem: (k: string, v: string) => void storage.set(k, String(v)),
  removeItem: (k: string) => void storage.delete(k),
  clear: () => storage.clear(),
});

let container: HTMLDivElement;
let root: Root;

function render() {
  act(() => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <DemoGuide />
      </NextIntlClientProvider>,
    );
  });
}

/** A reload: a fresh tree over the same storage. */
function reload() {
  act(() => root.unmount());
  root = createRoot(container);
  render();
}

function goTo(pathname: string) {
  env.pathname = pathname;
  render();
}

function byTestId(id: string) {
  return document.querySelector(`[data-testid="${id}"]`) as HTMLElement | null;
}

function strip() {
  return byTestId("demo-guide-strip");
}

async function pick(route: string) {
  await act(async () => {
    byTestId(`demo-guide-route-${route}`)!.click();
  });
}

function mutate(detail: Partial<MutationEventDetail>) {
  act(() => {
    window.dispatchEvent(
      new CustomEvent(MUTATION_EVENT, {
        detail: { method: "POST", status: 201, data: {}, path: "/", ...detail },
      }),
    );
  });
}

beforeEach(() => {
  storage.clear();
  env.pathname = "/coverage";
  env.persona = "admin";
  env.anchor = "a1a1a1a1-0000-4000-8000-000000000001";
  vi.mocked(chooseDemoGuide).mockClear();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

describe("Where to start", () => {
  it("is asked once, of the admin persona", async () => {
    render();
    expect(byTestId("demo-guide-dialog")).not.toBeNull();

    await pick("coverage");
    expect(chooseDemoGuide).toHaveBeenCalledWith("coverage");
    expect(byTestId("demo-guide-dialog")).toBeNull();

    reload();
    expect(byTestId("demo-guide-dialog")).toBeNull();
    expect(strip()?.dataset.route).toBe("coverage");
  });

  it("is never shown to the employee persona", () => {
    env.persona = "employee";
    render();
    expect(byTestId("demo-guide-dialog")).toBeNull();
    expect(strip()).toBeNull();
  });

  it("I'll look around is a pick too, and leaves no strip", async () => {
    render();
    await act(async () => {
      byTestId("demo-guide-skip")!.click();
    });
    expect(chooseDemoGuide).toHaveBeenCalledWith("skip");
    expect(strip()).toBeNull();
    reload();
    expect(byTestId("demo-guide-dialog")).toBeNull();
  });

  it("closing the window means I'll look around", async () => {
    render();
    await act(async () => {
      (document.querySelector('[data-slot="dialog-close"]') as HTMLElement).click();
    });
    expect(chooseDemoGuide).toHaveBeenCalledWith("skip");
    expect(strip()).toBeNull();
  });
});

describe("the route strip", () => {
  it("walks the plan route from the anchor assessment to the create", async () => {
    vi.useFakeTimers();
    render();
    await pick("pdp");

    expect(strip()?.dataset.step).toBe("1");
    expect(strip()?.textContent).toContain("Open a completed assessment.");
    expect(byTestId("demo-guide-go")?.getAttribute("href")).toBe(
      `/assessments/${env.anchor}`,
    );

    goTo(ASSESSMENT);
    expect(strip()?.dataset.step).toBe("2");
    // Already where the step happens: nothing to go to.
    expect(byTestId("demo-guide-go")).toBeNull();

    goTo("/development");
    expect(strip()?.dataset.step).toBe("3");
    expect(byTestId("demo-guide-go")?.getAttribute("href")).toBe(ASSESSMENT);

    // An assessment is not this route's create.
    mutate({ path: "/assessments", data: { employee_name: "X" } });
    expect(strip()?.dataset.step).toBe("3");

    mutate({ path: "/pdp", data: { title: "Plan", assessment_id: "a" } });
    expect(strip()?.dataset.step).toBe("done");
    expect(strip()?.textContent).toContain("Done");

    act(() => vi.advanceTimersByTime(6_000));
    expect(strip()).toBeNull();
    reload();
    expect(strip()).toBeNull();
    expect(byTestId("demo-guide-dialog")).toBeNull();
  });

  it("without an anchor the plan route starts from the list", async () => {
    env.anchor = null;
    render();
    await pick("pdp");
    expect(strip()?.textContent).toContain("Open an assessment with the Done status.");
    expect(byTestId("demo-guide-go")?.getAttribute("href")).toBe("/assessments");
  });

  it("the assessment route ends on a new assessment", async () => {
    render();
    await pick("assessment");
    goTo(ASSESSMENT);
    goTo("/assessments");
    expect(strip()?.dataset.step).toBe("3");
    mutate({ path: "/assessments", data: { employee_name: "Will" } });
    expect(strip()?.dataset.step).toBe("done");
  });

  it("the coverage route counts a process page, not /coverage/new", async () => {
    render();
    await pick("coverage");
    goTo("/coverage/new");
    expect(strip()?.dataset.step).toBe("1");
    goTo(PROCESS);
    expect(strip()?.dataset.step).toBe("2");

    // A hire need straight away (the steps were there) skips the breakdown.
    goTo("/coverage");
    expect(byTestId("demo-guide-go")?.getAttribute("href")).toBe(PROCESS);
    mutate({ path: "/work/containers/c1/gaps/hire-need" });
    expect(strip()?.dataset.step).toBe("done");
  });

  it("the cross ends the route for good", async () => {
    render();
    await pick("coverage");
    act(() => byTestId("demo-guide-close")!.click());
    expect(strip()).toBeNull();
    reload();
    expect(strip()).toBeNull();
    expect(byTestId("demo-guide-dialog")).toBeNull();
  });
});
