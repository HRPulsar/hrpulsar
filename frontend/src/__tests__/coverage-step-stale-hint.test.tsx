// @vitest-environment jsdom
//
// HRP-865 - a saved edit of the step's text does not reclassify it, and the
// row says so: a hint with the Reclassify action. No edit, no hint; an edit
// of the hours is not an edit of the text; a refused PATCH changed nothing;
// the hint outlives the tab switch that unmounts the editor and goes away
// once the step is reclassified.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { WorkStep } from "@/lib/api/work";

vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { updateStep: vi.fn(), reclassifyStep: vi.fn() },
}));
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { StepsEditor } = await import("@/components/coverage/steps-editor");
const { workApi } = await import("@/lib/api/work");

// The stale set is module state, so every test edits a step of its own.
function stepOf(id: string): WorkStep {
  return {
    id,
    container_id: "c-1",
    position: 1,
    title: "Draft the offer",
    description: "The first draft",
    responsibility: "none",
    reversibility: null,
    hours_per_run: null,
    runs_per_year: null,
    output_type: "draft",
    state: "system_suggested",
    gap_label: null,
    notes: null,
    executor_employee_id: null,
    accountable_employee_id: null,
    review_human_share: null,
    manual_mode: null,
    manual_pack_code: null,
    hourly_rate: null,
    primitive_codes: [],
    capabilities: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

let container: HTMLDivElement;
let root: Root;

function mount() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
}

function unmount() {
  act(() => root.unmount());
  container.remove();
}

beforeEach(() => {
  vi.mocked(workApi.updateStep).mockReset();
  vi.mocked(workApi.reclassifyStep).mockReset();
  mount();
});

afterEach(unmount);

async function render(step: WorkStep, canEdit = true) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <StepsEditor
          containerId="c-1"
          steps={[step]}
          primitives={[]}
          canEdit={canEdit}
          canAccept
          onStepsChange={() => {}}
          onAccepted={() => {}}
        />
      </NextIntlClientProvider>,
    );
  });
}

function part(step: WorkStep, name: string): HTMLElement | null {
  return document.querySelector(`[data-testid="coverage-step-row-${step.id}-${name}"]`);
}

async function edit(step: WorkStep, name: string, value: string) {
  const el = part(step, name) as HTMLInputElement | HTMLTextAreaElement;
  const proto =
    el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => {
    el.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
  });
}

it("labels the title and the description it edits", async () => {
  const step = stepOf("s-labels");
  await render(step);

  expect(part(step, "title")!.closest("label")!.textContent).toContain(
    enMessages.coverage.attrTitle,
  );
  expect(part(step, "description")!.closest("label")!.textContent).toContain(
    enMessages.coverage.attrDescription,
  );
});

it("shows the hint after a saved title edit and drops it after a reclassification", async () => {
  const step = stepOf("s-title");
  vi.mocked(workApi.updateStep).mockResolvedValue({ ...step, title: "Draft the contract" });
  vi.mocked(workApi.reclassifyStep).mockResolvedValue({ ...step, title: "Draft the contract" });
  await render(step);
  expect(part(step, "stale-hint")).toBeNull();

  await edit(step, "title", "Draft the contract");

  expect(workApi.updateStep).toHaveBeenCalledWith(step.id, { title: "Draft the contract" });
  expect(part(step, "stale-hint")!.textContent).toContain(
    enMessages.coverage.staleClassificationHint,
  );

  // The action is the existing dialog, not a second way to reclassify.
  await act(async () => part(step, "stale-hint-btn")!.click());
  const dialog = document.querySelector('[data-testid="coverage-modal-reclassify"]')!;
  expect(dialog).not.toBeNull();
  const comment = dialog.querySelector("textarea")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(
      comment,
      "It is a contract, not an offer",
    );
    comment.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => {
    dialog.querySelector("form")!.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
  });

  expect(workApi.reclassifyStep).toHaveBeenCalledTimes(1);
  expect(part(step, "stale-hint")).toBeNull();
});

it("shows the hint after a saved description edit", async () => {
  const step = stepOf("s-description");
  vi.mocked(workApi.updateStep).mockResolvedValue({ ...step, description: "Second draft" });
  await render(step);

  await edit(step, "description", "Second draft");

  expect(part(step, "stale-hint")).not.toBeNull();
});

it("stays silent when the hours change: the classifier never read them", async () => {
  const step = stepOf("s-hours");
  vi.mocked(workApi.updateStep).mockResolvedValue({ ...step, hours_per_run: 2 });
  await render(step);

  await edit(step, "input-hours", "2");

  expect(workApi.updateStep).toHaveBeenCalledWith(step.id, { hours_per_run: 2 });
  expect(part(step, "stale-hint")).toBeNull();
});

it("stays silent when the edit was refused", async () => {
  const step = stepOf("s-refused");
  vi.mocked(workApi.updateStep).mockRejectedValue(new Error("nope"));
  await render(step);

  await edit(step, "title", "Draft the contract");

  expect(workApi.updateStep).toHaveBeenCalledTimes(1);
  expect(part(step, "stale-hint")).toBeNull();
});

it("keeps the hint across the tab switch that unmounts the editor", async () => {
  const step = stepOf("s-remount");
  vi.mocked(workApi.updateStep).mockResolvedValue({ ...step, title: "Draft the contract" });
  await render(step);
  await edit(step, "title", "Draft the contract");
  expect(part(step, "stale-hint")).not.toBeNull();

  unmount();
  mount();
  await render({ ...step, title: "Draft the contract" });

  expect(part(step, "stale-hint")).not.toBeNull();
  // ... but a reader, who cannot reclassify, is not told to.
  await render({ ...step, title: "Draft the contract" }, false);
  expect(part(step, "stale-hint")).toBeNull();
});
