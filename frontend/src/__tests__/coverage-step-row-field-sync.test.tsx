// @vitest-environment jsdom
//
// HRP-810 review — a step row follows the record field by field. The
// response to one PATCH (the server echoes the whole step) used to reset
// every local input, so the number or the text being typed in a sibling
// field was thrown away mid-edit.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { WorkStep } from "@/lib/api/work";

vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { updateStep: vi.fn() },
}));
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { StepsEditor } = await import("@/components/coverage/steps-editor");

const STEP: WorkStep = {
  id: "s-1",
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
  primitive_codes: [],
  capabilities: [],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

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

async function render(step: WorkStep) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <StepsEditor
          containerId="c-1"
          steps={[step]}
          primitives={[]}
          canEdit
          canAccept
          onStepsChange={() => {}}
          onAccepted={() => {}}
        />
      </NextIntlClientProvider>,
    );
  });
}

function field(name: string): HTMLInputElement | HTMLTextAreaElement {
  return container.querySelector(
    `[data-testid="coverage-step-row-s-1-${name}"]`,
  ) as HTMLInputElement | HTMLTextAreaElement;
}

async function type(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto =
    el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

it("keeps the runs being typed when the hours come back from the server", async () => {
  await render(STEP);
  await type(field("input-runs"), "12");

  // The PATCH of hours_per_run answers with the whole step.
  await render({ ...STEP, hours_per_run: 3 });

  expect((field("input-runs") as HTMLInputElement).value).toBe("12");
  expect((field("input-hours") as HTMLInputElement).value).toBe("3");
});

// M22: the attribute existed in the model, the wire types and the test-id
// catalog, but no select ever rendered - so every breakdown shipped
// `reversibility=unknown`.
it("shows the reversibility of the step", async () => {
  await render(STEP);
  // The trigger renders its chevron glyph next to the label.
  expect(field("select-reversibility").textContent).toContain(
    enMessages.coverage.notSet,
  );

  await render({ ...STEP, reversibility: "costly" });

  expect(field("select-reversibility").textContent).toContain(
    enMessages.coverage.reversibility_costly,
  );
});

// 2.0.0 review §3: an out-of-range number used to be PATCHed on every
// blur, each one answered with a 422 and a toast.
it("does not send an estimate the backend would refuse", async () => {
  const { workApi } = await import("@/lib/api/work");
  await render(STEP);
  await type(field("input-hours"), "999");
  await act(async () => {
    field("input-hours").dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
  });

  expect(workApi.updateStep).not.toHaveBeenCalled();

  // ... and the corrected number still goes out: the refused one must not
  // be left marked as sent.
  await type(field("input-hours"), "2");
  await act(async () => {
    field("input-hours").dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
  });

  expect(workApi.updateStep).toHaveBeenCalledTimes(1);
});

it("keeps the description being typed when the title comes back", async () => {
  await render(STEP);
  await type(field("description"), "A longer note");

  await render({ ...STEP, title: "Draft the contract" });

  expect(field("description").value).toBe("A longer note");
  expect((field("title") as HTMLInputElement).value).toBe("Draft the contract");
});
