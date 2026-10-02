// @vitest-environment jsdom
//
// HRP-853: a process opened by a direct link that the access rules hide, or
// that was deleted, answers 404 - the page says it was not found and offers
// the list, instead of "Load failed" with a retry, which stays for a network
// or server error.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import { ApiError } from "@/lib/api";

const getContainer = vi.fn();
const listSteps = vi.fn();
const listPrimitives = vi.fn();
const latestDecomposition = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "gone" }),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { getContainer, listSteps, listPrimitives, latestDecomposition },
}));
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { default: ContainerPage } = await import("@/app/(dashboard)/coverage/[id]/page");

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  getContainer.mockReset();
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

const byId = (id: string) => document.querySelector<HTMLElement>(`[data-testid="${id}"]`);

it("says a hidden or deleted process was not found, with a way back to the list", async () => {
  getContainer.mockRejectedValue(new ApiError(404, "not found"));

  await render();

  expect(byId("coverage-detail-not-found")!.textContent).toContain(enMessages.coverage.notFound);
  expect(byId("coverage-detail-not-found-link")!.getAttribute("href")).toBe("/coverage");
  expect(byId("coverage-detail-load-failed")).toBeNull();
});

it("keeps Load failed with a retry for a server error", async () => {
  getContainer.mockRejectedValue(new ApiError(500, "boom"));

  await render();

  expect(byId("coverage-detail-load-failed")).not.toBeNull();
  expect(byId("coverage-detail-load-retry")).not.toBeNull();
  expect(byId("coverage-detail-not-found")).toBeNull();
});
