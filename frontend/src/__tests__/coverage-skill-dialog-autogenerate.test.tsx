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
const toastSuccess = vi.fn();

vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { getSkill, generateSkill },
}));
let authUser: { tenant_is_demo?: boolean } | null = null;
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: authUser }) }));
vi.mock("@/hooks/use-cost-confirmation", () => ({
  useCostConfirmation: () => ({ cost: null, threshold: 0, requiresConfirmation: false }),
}));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: vi.fn() } }));

const { SkillDialog } = await import("@/components/coverage/skill-dialog");

const SKILL: StepSkill = {
  id: "sk-1",
  step_id: "s-1",
  pack_id: null,
  status: "ready",
  skill_name: null,
  content: null,
  error_code: null,
  error_message: null,
  generated_at: "2026-01-01T00:00:00Z",
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  getSkill.mockReset();
  generateSkill.mockReset();
  toastSuccess.mockReset();
  authUser = null;
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
          step={{ step_id: "s-1", position: 3, title: "Draft the offer", skill_status: status }}
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
  const onClose = vi.fn();

  await open("none", onClose);

  expect(generateSkill).not.toHaveBeenCalled();
  expect(byId("coverage-modal-skill")).toBeNull();
  expect(document.body.textContent).toContain(enMessages.coverage.skillConfirm);
  expect(byId("coverage-skill-confirm-btn-confirm")!.textContent).toBe(enMessages.coverage.getSkill);

  await click("coverage-skill-confirm-btn-confirm");

  expect(generateSkill).toHaveBeenCalledWith("s-1");
  expect(byId("coverage-skill-confirm-btn-confirm")).toBeNull();
  // HRP-1202: queued, not awaited - the reader goes back to the process,
  // told the step updates by itself; no progress modal holds them.
  expect(byId("coverage-modal-skill")).toBeNull();
  expect(onClose).toHaveBeenCalled();
  expect(toastSuccess.mock.calls[0][0]).toContain("step 3 is being written");
});

it("leaves a generation started elsewhere to the page instead of waiting in the modal", async () => {
  getSkill.mockResolvedValue({ ...SKILL, status: "generating" });
  const onClose = vi.fn();

  await open("generating", onClose);

  expect(generateSkill).not.toHaveBeenCalled();
  expect(byId("coverage-modal-skill")).toBeNull();
  expect(onClose).toHaveBeenCalled();
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

it("says the file follows the AI content language (HRP-912)", async () => {
  getSkill.mockResolvedValue({ ...SKILL, content: "# Draft the offer" });

  await open("ready");

  expect(document.body.textContent).toContain(enMessages.coverage.skillLanguageHint);
});

it("keeps the language line off a window with no file in it (HRP-1182)", async () => {
  getSkill.mockResolvedValue({ ...SKILL, content: "" });

  await open("ready");

  expect(byId("coverage-modal-skill")).not.toBeNull();
  expect(document.body.textContent).not.toContain(enMessages.coverage.skillLanguageHint);
});

// HRP-1201: a demo visitor has no agent of their own - the dialog says in
// one line where the file goes, next to the download; nothing asks for an
// agent first. Outside the demo the text is the one it always was.
it.each([
  ["the demo", { tenant_is_demo: true }, enMessages.coverage.skillTextDemo],
  ["a company workspace", { tenant_is_demo: false }, enMessages.coverage.skillText],
])("in %s says where the file goes", async (_name, user, text) => {
  authUser = user;
  getSkill.mockResolvedValue({ ...SKILL, content: "# Draft the offer" });

  await open("ready");

  expect(byId("coverage-skill-text")!.textContent).toBe(text);
  expect(byId("coverage-btn-skill-download")!.hasAttribute("disabled")).toBe(false);
});
