// @vitest-environment jsdom
//
// HRP-801 REDO (QA 23.10, b-d): "Based on {process}" on a vacancy and on its
// talent card. The title links to the coverage only for a reader who may
// open it; a vacancy that came from no process shows no line.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { HireNeedOrigin } from "@/lib/api/work";

const vacancyOrigin = vi.fn();
const talentCardOrigin = vi.fn();

vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { vacancyOrigin, talentCardOrigin },
}));

const { HireNeedOriginLine } = await import("@/components/coverage/hire-need-origin");

const ORIGIN: HireNeedOrigin = {
  container_id: "c-1",
  type: "process",
  title: "Counterparty onboarding",
  can_open: true,
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vacancyOrigin.mockReset();
  talentCardOrigin.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render(props: { vacancyId?: string; talentCardId?: string }) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <HireNeedOriginLine {...props} />
      </NextIntlClientProvider>,
    );
  });
}

const byId = (id: string) => container.querySelector(`[data-testid="${id}"]`);

it("names the process of a vacancy and links to its coverage", async () => {
  vacancyOrigin.mockResolvedValue(ORIGIN);
  await render({ vacancyId: "v-1" });
  expect(vacancyOrigin).toHaveBeenCalledWith("v-1");
  expect(byId("hire-need-origin")!.textContent).toContain(enMessages.coverage.originLabel_process);
  expect(byId("hire-need-origin-link")!.getAttribute("href")).toBe("/coverage/c-1");
  expect(byId("hire-need-origin-link")!.textContent).toBe("Counterparty onboarding");
});

it("names a project of a talent card as text for a reader who cannot open it", async () => {
  talentCardOrigin.mockResolvedValue({ ...ORIGIN, type: "initiative", can_open: false });
  await render({ talentCardId: "tc-1" });
  expect(talentCardOrigin).toHaveBeenCalledWith("tc-1");
  expect(byId("hire-need-origin")!.textContent).toContain(enMessages.coverage.originLabel_initiative);
  expect(byId("hire-need-origin-link")).toBeNull();
  expect(byId("hire-need-origin-title")!.textContent).toBe("Counterparty onboarding");
});

it("shows nothing for a vacancy from no process, or when the read fails", async () => {
  vacancyOrigin.mockResolvedValue(null);
  await render({ vacancyId: "v-1" });
  expect(byId("hire-need-origin")).toBeNull();

  vacancyOrigin.mockRejectedValue(new Error("403"));
  await render({ vacancyId: "v-2" });
  expect(byId("hire-need-origin")).toBeNull();
});
