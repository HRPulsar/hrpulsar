// @vitest-environment jsdom
//
// 2.0.0 review §3 — walking from /coverage/A to /coverage/B kept the page
// mounted, so B's title arrived on top of A's steps, A's banner and A's
// coverage tab until every request came back.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { WorkContainer } from "@/lib/api/work";

let currentId = "a";

const getContainer = vi.fn();
const listSteps = vi.fn();
const listPrimitives = vi.fn();
const latestDecomposition = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: currentId }),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { getContainer, listSteps, listPrimitives, latestDecomposition },
}));
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { default: ContainerPage } = await import("@/app/(dashboard)/coverage/[id]/page");

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
  my_access: "read",
  coverage_summary: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  currentId = "a";
  getContainer.mockReset().mockResolvedValue(CONTAINER);
  listSteps.mockReset().mockResolvedValue([]);
  listPrimitives.mockReset().mockResolvedValue([]);
  latestDecomposition.mockReset().mockResolvedValue(null);
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
        <ContainerPage />
      </NextIntlClientProvider>,
    );
  });
}

it("drops the previous process when the id changes", async () => {
  await render();
  expect(container.textContent).toContain("Month-end close");

  // The second process is still loading.
  currentId = "b";
  getContainer.mockReturnValue(new Promise(() => {}));
  await render();

  expect(container.textContent).not.toContain("Month-end close");
  expect(container.textContent).toContain(enMessages.common.loading);
});
