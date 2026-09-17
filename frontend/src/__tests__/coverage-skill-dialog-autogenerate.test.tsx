// @vitest-environment jsdom
//
// 2.0.0 review §3 — opening a step whose skill row says "ready" but comes
// back without content used to fire a generation nobody asked for, and the
// generation is a billed action.

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

async function open(status: SkillStatus) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <SkillDialog
          step={{ step_id: "s-1", title: "Draft the offer", skill_status: status }}
          canEdit
          onClose={() => {}}
          onChanged={() => {}}
        />
      </NextIntlClientProvider>,
    );
  });
}

it("does not regenerate a ready skill that came back empty", async () => {
  getSkill.mockResolvedValue(SKILL);

  await open("ready");

  expect(generateSkill).not.toHaveBeenCalled();
  expect(document.body.textContent).toContain(enMessages.coverage.skillEmpty);
});

it("still generates the first skill of a step", async () => {
  generateSkill.mockResolvedValue({ ...SKILL, status: "generating" });

  await open("none");

  expect(generateSkill).toHaveBeenCalledWith("s-1");
});

it("says the file is English by design", async () => {
  getSkill.mockResolvedValue({ ...SKILL, content: "# Draft the offer" });

  await open("ready");

  expect(document.body.textContent).toContain(enMessages.coverage.skillEnglishHint);
});
