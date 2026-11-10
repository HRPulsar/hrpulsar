// @vitest-environment jsdom
//
// HRP-949 REDO: "See what changes: N → M steps" read as plain text - nothing
// said the line opens. A chevron in front of it turns when the preview opens,
// the way the step details do (HRP-904).

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { DecompositionSession, WorkContainer, WorkStep } from "@/lib/api/work";

const never = () => new Promise(() => {});

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "a" }),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/lib/api/work", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/work")>();
  // Only the page's own reads answer; the tabs below it stay loading.
  const workApi = new Proxy(
    {
      getContainer: () => Promise.resolve(CONTAINER),
      listSteps: () => Promise.resolve([STEP]),
      listPrimitives: () => Promise.resolve([]),
      latestDecomposition: () => Promise.resolve(SESSION),
    } as Record<string, () => Promise<unknown>>,
    { get: (target, key: string) => target[key] ?? never },
  );
  return { ...actual, workApi };
});
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const CONTAINER: WorkContainer = {
  id: "a",
  tenant_id: "t-1",
  type: "process",
  title: "Month-end close",
  description: null,
  goal: null,
  status: "draft",
  visibility: "restricted",
  owner_id: null,
  created_by_id: null,
  source: "manual",
  catalog_version: "v1.1",
  gap_default_label: "hire",
  my_access: "edit",
  coverage_summary: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const STEP = { id: "s-1", container_id: "a", position: 1, title: "Collect invoices" } as WorkStep;

const SESSION: DecompositionSession = {
  id: "d-1",
  container_id: "a",
  status: "ready",
  phase: null,
  error_code: null,
  error_message: null,
  payload: { steps: [{ title: "Collect" }, { title: "Check" }] as never },
  created_at: "2026-01-01T00:00:00Z",
  finished_at: "2026-01-01T00:00:00Z",
};

const { default: ContainerPage } = await import("@/app/(dashboard)/coverage/[id]/page");

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

it("marks the draft preview with a chevron that turns when open", async () => {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <ContainerPage />
      </NextIntlClientProvider>,
    );
  });
  const details = container.querySelector('[data-testid="coverage-draft-preview"]')!;
  expect(details.getAttribute("class")).toContain("group");
  const summary = details.querySelector("summary")!;
  const chevron = summary.querySelector('[data-testid="coverage-draft-preview-chevron"]');
  expect(chevron).not.toBeNull();
  expect(chevron!.getAttribute("class")).toContain("group-open:rotate-90");
  expect(summary.textContent).toBe("See what changes: 1 → 2 steps");
});
