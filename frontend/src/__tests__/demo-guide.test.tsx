// @vitest-environment jsdom
//
// The sandbox's start routes (HRP-1159): "Where to start" once, to the
// admin persona only; the pick opens the page the route starts on
// (HRP-1175); every step is something the visitor does (HRP-1178), its
// button ringed once it is on the page (HRP-1177); the strip goes once
// the route's create is done.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

const ANCHOR = "/assessments/a1a1a1a1-0000-4000-8000-000000000001";
const EMPTY = "/coverage/e0e0e0e0-0000-4000-8000-000000000004";
const GAP = "/coverage/9a9a9a9a-0000-4000-8000-000000000005";
const PROCESS = "/coverage/c0c0c0c0-0000-4000-8000-000000000002";

type Starts = {
  assessment_id: string | null;
  process_id: string | null;
  gap_process_id: string | null;
};

const env = vi.hoisted(() => ({
  pathname: "/coverage",
  persona: "admin" as "admin" | "employee",
  /** What `POST /demo/guide` answers; null fails the request. */
  starts: null as Starts | null,
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => env.pathname,
  useRouter: () => ({ push: env.push }),
}));
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    user: { tenant_id: "t-demo", tenant_is_demo: true, demo_persona: env.persona },
  }),
}));
vi.mock("@/lib/demo", () => ({
  saveDemoAccess: vi.fn(),
  chooseDemoGuide: vi.fn(() =>
    env.starts ? Promise.resolve(env.starts) : Promise.reject(new Error("down")),
  ),
}));

import { DemoGuide } from "@/components/dashboard/demo-guide";
import { MUTATION_EVENT, type MutationEventDetail } from "@/lib/api";
import { chooseDemoGuide } from "@/lib/demo";

const STORAGE_KEY = "demo_guide:t-demo";
const id = (href: string) => href.split("/")[2];
const SEEDED: Starts = {
  assessment_id: id(ANCHOR),
  process_id: id(EMPTY),
  gap_process_id: id(GAP),
};
const NOTHING: Starts = { assessment_id: null, process_id: null, gap_process_id: null };

const storage = new Map<string, string>();
vi.stubGlobal("localStorage", {
  getItem: (k: string) => storage.get(k) ?? null,
  setItem: (k: string, v: string) => void storage.set(k, String(v)),
  removeItem: (k: string) => void storage.delete(k),
  clear: () => storage.clear(),
});

let container: HTMLDivElement;
let page: HTMLDivElement;
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

/** A page change: the old page's buttons go with it. */
async function goTo(pathname: string) {
  env.pathname = pathname;
  page.replaceChildren();
  await act(async () => render());
}

/** A button of the current page, put on screen the way a list that has
 * loaded or a tab that was opened does it: after the strip rendered. */
async function show(testId: string) {
  const el = document.createElement("button");
  el.dataset.testid = testId;
  await act(async () => {
    page.appendChild(el);
  });
  return el;
}

const scrolled = vi.fn();

const ringed = () =>
  [...document.querySelectorAll("[data-demo-guide-target]")].map(
    (el) => (el as HTMLElement).dataset.testid,
  );

function byTestId(id: string) {
  return document.querySelector(`[data-testid="${id}"]`) as HTMLElement | null;
}

function strip() {
  return byTestId("demo-guide-strip");
}

const go = () => byTestId("demo-guide-go")?.getAttribute("href") ?? null;

/** Pick a route and land where the pick leads. */
async function pick(route: string) {
  await act(async () => {
    byTestId(`demo-guide-route-${route}`)!.click();
  });
  const landed = env.push.mock.calls.at(-1)?.[0] as string | undefined;
  if (landed) await goTo(landed);
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
  env.starts = SEEDED;
  env.push.mockClear();
  vi.mocked(chooseDemoGuide).mockClear();
  // jsdom lays nothing out and has no scrollIntoView of its own.
  scrolled.mockClear();
  Element.prototype.scrollIntoView = function (this: Element, how?: unknown) {
    scrolled((this as HTMLElement).dataset.testid, how);
  };
  container = document.createElement("div");
  page = document.createElement("div");
  document.body.append(container, page);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  page.remove();
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

  it.each([
    ["coverage", EMPTY],
    ["pdp", ANCHOR],
    ["assessment", ANCHOR],
  ])("the %s pick opens the page its route starts on", async (route, start) => {
    render();
    await pick(route);
    expect(env.push).toHaveBeenCalledExactlyOnceWith(start);
    expect(strip()?.dataset.step).toBe("1");
    // Already there, and no "open" step to do first.
    expect(strip()?.textContent).toContain("Step 1 of 2:");
  });

  it.each([
    ["coverage", "/coverage", "Open a process in Coverage."],
    ["pdp", "/assessments", "Open an assessment with the Done status."],
    [
      "assessment",
      "/assessments",
      "Open the results of an assessment with the Done status.",
    ],
  ])("with nothing to start from, %s leads from the list", async (route, list, text) => {
    env.starts = NOTHING;
    render();
    await pick(route);
    expect(env.push).toHaveBeenCalledExactlyOnceWith(list);
    expect(strip()?.textContent).toBe(`Step 1 of 3: ${text}`);
  });

  it("a failed request still starts the route, from the list", async () => {
    env.starts = null;
    render();
    await pick("pdp");
    expect(env.push).toHaveBeenCalledExactlyOnceWith("/assessments");
    expect(strip()?.textContent).toContain("Step 1 of 3:");
  });

  it("an answer that never comes does not hold the window", async () => {
    vi.useFakeTimers();
    vi.mocked(chooseDemoGuide).mockReturnValueOnce(new Promise(() => {}));
    render();
    await act(async () => {
      byTestId("demo-guide-route-assessment")!.click();
    });
    // Waiting: one pick only, and no way to stack another on it.
    expect(byTestId("demo-guide-dialog")).not.toBeNull();
    await act(async () => {
      byTestId("demo-guide-route-pdp")!.click();
      byTestId("demo-guide-skip")!.click();
    });
    expect(chooseDemoGuide).toHaveBeenCalledExactlyOnceWith("assessment");
    expect(env.push).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(byTestId("demo-guide-dialog")).toBeNull();
    expect(env.push).toHaveBeenCalledExactlyOnceWith("/assessments");
    expect(strip()?.dataset.route).toBe("assessment");
    expect(strip()?.textContent).toContain("Step 1 of 3:");
  });

  it("I'll look around is a pick too: no strip, and nowhere to go", async () => {
    render();
    await act(async () => {
      byTestId("demo-guide-skip")!.click();
    });
    expect(chooseDemoGuide).toHaveBeenCalledWith("skip");
    expect(env.push).not.toHaveBeenCalled();
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
    expect(env.push).not.toHaveBeenCalled();
    expect(strip()).toBeNull();
  });

  it.each([
    ["a route in progress", { path: "assessment", step: 2, anchor: id(ANCHOR), back: ANCHOR }],
    ["a finished route", { path: "coverage", step: 3, anchor: null, back: PROCESS }],
    ["I'll look around", { path: "skip", step: 0, anchor: null, back: null }],
  ])("a 2.6.0 sandbox with %s is neither asked again nor resumed", (_, stored) => {
    storage.set(STORAGE_KEY, JSON.stringify(stored));
    render();
    expect(byTestId("demo-guide-dialog")).toBeNull();
    expect(strip()).toBeNull();
    reload();
    expect(byTestId("demo-guide-dialog")).toBeNull();
    expect(strip()).toBeNull();
  });
});

describe("the route strip", () => {
  it("walks the plan route from the growth zones to the create", async () => {
    vi.useFakeTimers();
    render();
    await pick("pdp");

    expect(strip()?.textContent).toBe(
      "Step 1 of 2: Under Growth zones, click Create development plan.",
    );
    // On the step's page: nothing to go to, and the button is ringed
    // once the assessment has loaded.
    expect(go()).toBeNull();
    const createPlan = await show("assessment-create-plan");
    expect(ringed()).toEqual(["assessment-create-plan"]);
    // Brought into view once, under the strip - and the focus stays put.
    expect(scrolled.mock.calls).toEqual([["assessment-create-plan", { block: "start" }]]);
    expect(document.activeElement).not.toBe(createPlan);
    await show("another-button-of-the-page");
    expect(scrolled).toHaveBeenCalledOnce();

    // Development through the menu is not the step.
    await goTo("/development");
    expect(strip()?.dataset.step).toBe("1");
    expect(go()).toBe(ANCHOR);
    expect(ringed()).toEqual([]);

    await goTo(ANCHOR);
    const again = await show("assessment-create-plan");
    expect(createPlan).not.toBe(again);
    await act(async () => again.click());
    expect(strip()?.textContent).toBe("Step 2 of 2: Check the plan and click Create.");

    await goTo("/development");
    await show("development-create-submit");
    expect(ringed()).toEqual(["development-create-submit"]);
    expect(go()).toBeNull();

    // An assessment is not this route's create.
    mutate({ path: "/assessments", data: { employee_name: "X" } });
    expect(strip()?.dataset.step).toBe("2");

    mutate({ path: "/pdp", data: { title: "Plan", assessment_id: "a" } });
    expect(strip()?.dataset.step).toBe("done");
    expect(strip()?.textContent).toContain("Done");
    expect(ringed()).toEqual([]);

    act(() => vi.advanceTimersByTime(6_000));
    expect(strip()).toBeNull();
    reload();
    expect(strip()).toBeNull();
    expect(byTestId("demo-guide-dialog")).toBeNull();
  });

  it("the plan dialog closed half way: Go leads back to the button", async () => {
    render();
    await pick("pdp");
    await act(async () => (await show("assessment-create-plan")).click());
    await goTo("/development");
    expect(go()).toBe(ANCHOR);
    await goTo(ANCHOR);
    await show("assessment-create-plan");
    expect(ringed()).toEqual(["assessment-create-plan"]);
    expect(go()).toBeNull();
  });

  it("the assessment route ends on the create, with the list on the way", async () => {
    render();
    await pick("assessment");

    expect(strip()?.textContent).toBe(
      "Step 1 of 2: Look through the results of a completed assessment, " +
        "then go to Assessments to start one yourself.Go",
    );
    // On the results "Go" is "next"; anywhere else it leads to them.
    expect(go()).toBe("/assessments");
    await goTo("/dashboard");
    expect(go()).toBe(ANCHOR);

    await goTo("/assessments");
    expect(strip()?.textContent).toBe(
      "Step 2 of 2: Click Create assessment, choose Single employee, " +
        "pick an employee and click Create.",
    );
    expect(go()).toBeNull();
    await show("assessments-btn-create");
    expect(ringed()).toEqual(["assessments-btn-create"]);
    // The ring follows the dialog: the mode, then the form's Create.
    await show("assessments-modal-mode-btn-single");
    expect(ringed()).toEqual(["assessments-modal-mode-btn-single"]);
    // In a dialog the button is only brought as far as it must be: the
    // fields the step asks to fill come before it.
    const form = document.createElement("div");
    form.setAttribute("role", "dialog");
    const submit = document.createElement("button");
    submit.dataset.testid = "assessments-modal-create-btn-submit";
    form.appendChild(submit);
    await act(async () => {
      page.appendChild(form);
    });
    expect(ringed()).toEqual(["assessments-modal-create-btn-submit"]);
    expect(scrolled.mock.calls.at(-1)).toEqual([
      "assessments-modal-create-btn-submit",
      { block: "nearest" },
    ]);

    // Back on the results (the browser's Back): the same step, and a way
    // to its button.
    await goTo(ANCHOR);
    expect(strip()?.dataset.step).toBe("2");
    expect(go()).toBe("/assessments");
    expect(ringed()).toEqual([]);

    mutate({ path: "/assessments", data: { employee_name: "Will" } });
    expect(strip()?.dataset.step).toBe("done");
  });

  it("the coverage route breaks down the empty process, then hires", async () => {
    render();
    await pick("coverage");

    expect(strip()?.textContent).toBe(
      "Step 1 of 2: Click Generate steps and wait while AI breaks the process into steps.",
    );
    expect(go()).toBeNull();
    await show("coverage-btn-generate");
    expect(ringed()).toEqual(["coverage-btn-generate"]);

    // On a process that has steps the same button reads "Regenerate
    // steps": no ring there, and a way back.
    await goTo(PROCESS);
    await show("coverage-btn-generate");
    expect(ringed()).toEqual([]);
    expect(go()).toBe(EMPTY);

    await goTo(EMPTY);
    mutate({ path: "/work/decomposition/sessions/s1/apply" });
    expect(strip()?.textContent).toBe(
      "Step 2 of 2: Open the To do tab, select a step under Nobody does this yet, " +
        "click Open hire need and confirm.Go",
    );
    // The fresh breakdown may hold no such step: "Go" knows a process
    // that does - until this one shows the button.
    expect(go()).toBe(GAP);
    await show("coverage-gap-btn-hire-need");
    expect(go()).toBeNull();
    expect(ringed()).toEqual(["coverage-gap-btn-hire-need"]);

    await goTo(GAP);
    expect(go()).toBeNull();
    mutate({ path: "/work/containers/c1/gaps/hire-need" });
    expect(strip()?.dataset.step).toBe("done");
  });

  it("a hire need straight away skips the breakdown", async () => {
    render();
    await pick("coverage");
    mutate({ path: "/work/containers/c1/gaps/hire-need" });
    expect(strip()?.dataset.step).toBe("done");
  });

  it("without an anchor the steps are fixed at the pick: open, then the same two", async () => {
    env.starts = NOTHING;
    render();
    await pick("coverage");
    await goTo("/coverage/new");
    expect(strip()?.dataset.step).toBe("1");

    await goTo(PROCESS);
    expect(strip()?.textContent).toBe(
      "Step 2 of 3: Click Generate steps or Regenerate steps, " +
        "then Apply once the draft is ready.",
    );
    await show("coverage-btn-generate");
    expect(ringed()).toEqual(["coverage-btn-generate"]);

    reload();
    expect(strip()?.textContent).toContain("Step 2 of 3:");
    await goTo("/coverage");
    expect(go()).toBe(PROCESS);
  });

  it("the ring goes with the route", async () => {
    render();
    await pick("coverage");
    const generate = await show("coverage-btn-generate");
    expect(generate.hasAttribute("data-demo-guide-target")).toBe(true);
    act(() => byTestId("demo-guide-close")!.click());
    expect(generate.hasAttribute("data-demo-guide-target")).toBe(false);
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
