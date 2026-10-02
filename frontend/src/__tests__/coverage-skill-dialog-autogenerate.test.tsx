// @vitest-environment jsdom
//
// 2.0.0 review §3 — opening a step whose skill row says "ready" but comes
// back without content used to fire a generation nobody asked for, and the
// generation is a billed action. HRP-960: the first generation (and a retry)
// waits for a confirmation; Cancel closes without a request.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { SkillStatus, StepSkill } from "@/lib/api/work";

const getSkill = vi.fn();
const generateSkill = vi.fn();

vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { getSkill, generateSkill },
}));
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("@/hooks/use-cost-confirmation", () => ({
  useCostConfirmation: () => ({ cost: null, threshold: 0, requiresConfirmation: false }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { SkillDialog } = await import("@/components/coverage/skill-dialog");

const SKILL: StepSkill = {
  id: "sk-1",
  step_id: "s-1",
  pack_id: null,
  status: "ready",
  skill_name: null,
  content: null,
  error_message: null,
  generated_at: "2026-01-01T00:00:00Z",
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  getSkill.mockReset();
  generateSkill.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function open(status: SkillStatus, onClose: () => void = () => {}) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <SkillDialog
          step={{ step_id: "s-1", title: "Draft the offer", skill_status: status }}
          canEdit
          onClose={onClose}
          onChanged={() => {}}
        />
      </NextIntlClientProvider>,
    );
  });
}

const byId = (id: string) => document.querySelector<HTMLElement>(`[data-testid="${id}"]`);

async function click(testId: string) {
  const el = byId(testId);
  expect(el, testId).toBeTruthy();
  await act(async () => {
    el!.click();
  });
}

it("does not regenerate a ready skill that came back empty", async () => {
  getSkill.mockResolvedValue(SKILL);

  await open("ready");

  expect(generateSkill).not.toHaveBeenCalled();
  // Nothing to charge for: no confirmation in the way of reading it.
  expect(byId("coverage-skill-confirm-btn-confirm")).toBeNull();
  expect(document.body.textContent).toContain(enMessages.coverage.skillEmpty);
});

it("asks before the first skill of a step, and generates once confirmed", async () => {
  generateSkill.mockResolvedValue({ ...SKILL, status: "generating" });

  await open("none");

  expect(generateSkill).not.toHaveBeenCalled();
  expect(byId("coverage-modal-skill")).toBeNull();
  expect(document.body.textContent).toContain(enMessages.coverage.skillConfirm);
  expect(byId("coverage-skill-confirm-btn-confirm")!.textContent).toBe(enMessages.coverage.getSkill);

  await click("coverage-skill-confirm-btn-confirm");

  expect(generateSkill).toHaveBeenCalledWith("s-1");
  expect(byId("coverage-skill-confirm-btn-confirm")).toBeNull();
  expect(byId("coverage-modal-skill")).not.toBeNull();
});

it("cancel closes without a request", async () => {
  const onClose = vi.fn();

  await open("none", onClose);
  await click("coverage-skill-confirm-btn-cancel");

  expect(onClose).toHaveBeenCalled();
  expect(generateSkill).not.toHaveBeenCalled();
});

it("asks again before retrying a failed skill", async () => {
  getSkill.mockResolvedValue({ ...SKILL, status: "failed", error_message: "boom" });
  generateSkill.mockResolvedValue({ ...SKILL, status: "generating" });

  await open("failed");

  expect(generateSkill).not.toHaveBeenCalled();
  await click("coverage-skill-confirm-btn-confirm");
  expect(generateSkill).toHaveBeenCalledWith("s-1");
});

it("opens a failed regeneration on the skill it kept, with no confirmation", async () => {
  // Review 01.10: the confirmation promised a charged generation that the
  // dialog then never ran - the step still had its previous content.
  getSkill.mockResolvedValue({
    ...SKILL,
    status: "failed",
    error_message: "boom",
    content: "# Draft the offer",
  });

  await open("failed");

  expect(byId("coverage-skill-confirm-btn-confirm")).toBeNull();
  expect(byId("coverage-modal-skill")).not.toBeNull();
  expect(document.body.textContent).toContain("boom");
  expect(generateSkill).not.toHaveBeenCalled();
});

it("says the file is English by design", async () => {
  getSkill.mockResolvedValue({ ...SKILL, content: "# Draft the offer" });

  await open("ready");

  expect(document.body.textContent).toContain(enMessages.coverage.skillEnglishHint);
});
