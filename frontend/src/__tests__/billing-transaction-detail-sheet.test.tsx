// @vitest-environment jsdom
//
// HRP-965: the transaction sheet shows who / object link / model /
// duration / call count, and hides the calls block when there is none.
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import enMessages from "../../messages/en.json";
import type { CreditTransactionDetail } from "@/lib/types";

let detail: CreditTransactionDetail;

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: { get: vi.fn(() => Promise.resolve(detail)) },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { toast } from "sonner";
import { api } from "@/lib/api";
import { TransactionDetailSheet } from "@/components/billing/transaction-detail-sheet";

const getMock = vi.mocked(api.get);

const base: CreditTransactionDetail = {
  id: "tx-1", amount: -12, credit_type: "free", action: "recruitment.generate_profile",
  entity_type: "vacancy", entity_id: "v-1", balance_after_free: 88, balance_after_paid: 0,
  balance_after_bonus: 0, created_at: "2026-09-25T14:32:00Z",
  user_id: "u-1", user_name: "Anna Petrova", work_unit_id: "w-1",
  entity: { type: "vacancy", id: "v-1", title: "Frontend Developer", path: "/recruitment/requisitions/v-1" },
  // HRP-1046: wall_time_ms < total_latency_ms — parallel calls; the sheet
  // must show the wall time, not the latency sum.
  calls: { count: 3, models: ["claude-sonnet-4-5"], total_latency_ms: 48_400, wall_time_ms: 30_200, started_at: null, finished_at: null },
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  getMock.mockClear();
  vi.mocked(toast.error).mockClear();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function mount(transactionId = "tx-1", onOpenChange: (open: boolean) => void = () => {}) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <TransactionDetailSheet transactionId={transactionId} open onOpenChange={onOpenChange} />
      </NextIntlClientProvider>,
    );
  });
  await act(async () => {});
}

const sheetText = () => document.querySelector('[data-testid="settings-billing-tx-sheet"]')?.textContent;

describe("TransactionDetailSheet", () => {
  it("renders who, the object link, model, duration and call count", async () => {
    detail = base;
    await mount();
    const sheet = document.querySelector('[data-testid="settings-billing-tx-sheet"]');
    expect(sheet?.textContent).toContain("Anna Petrova");
    const link = document.querySelector('[data-testid="settings-billing-tx-object-link"]') as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/recruitment/requisitions/v-1");
    expect(link.textContent).toContain("Frontend Developer");
    expect(sheet?.textContent).toContain("claude-sonnet-4-5");
    // Wall time, not the 48 s latency sum (HRP-1046).
    expect(sheet?.textContent).toContain("30 s");
    expect(sheet?.textContent).not.toContain("48 s");
    expect(sheet?.textContent).toContain("3");
  });

  it("shows the type without a link for a deleted object and no calls block", async () => {
    detail = { ...base, entity: { type: "vacancy", id: "v-1", title: null, path: null }, calls: null };
    await mount();
    expect(document.querySelector('[data-testid="settings-billing-tx-object-link"]')).toBeNull();
    const sheet = document.querySelector('[data-testid="settings-billing-tx-sheet"]');
    expect(sheet?.textContent).toContain("Requisition");
    expect(document.querySelector('[data-testid="settings-billing-tx-calls"]')).toBeNull();
  });

  it("labels a system transaction", async () => {
    detail = { ...base, user_id: null, user_name: null, entity: null, calls: null };
    await mount();
    expect(document.querySelector('[data-testid="settings-billing-tx-sheet"]')?.textContent).toContain("System");
  });

  it("links a titleless object by its type label when a path is still known (R15)", async () => {
    detail = { ...base, entity: { type: "vacancy", id: "v-1", title: null, path: "/recruitment/requisitions/v-1" } };
    await mount();
    const link = document.querySelector('[data-testid="settings-billing-tx-object-link"]') as HTMLAnchorElement;
    expect(link).not.toBeNull();
    expect(link.getAttribute("href")).toBe("/recruitment/requisitions/v-1");
    expect(link.textContent).toContain("Requisition");
  });

  it("fetches once per open even when the parent re-renders with a new onOpenChange (fix round 1)", async () => {
    detail = base;
    await mount();
    expect(getMock).toHaveBeenCalledTimes(1);

    // Same `open` / `transactionId`, but `mount()` passes a fresh inline
    // arrow each call — exactly what the transactions page does on every
    // re-render. Before the fix, `onOpenChange` sat in the fetch effect's
    // deps, so this second render reset `detail` to null and re-fetched.
    await mount();
    expect(getMock).toHaveBeenCalledTimes(1);
  });

  it("toasts and closes when the detail cannot be loaded", async () => {
    getMock.mockImplementationOnce(() => Promise.reject(new Error("404")));
    const onOpenChange = vi.fn();
    await mount("tx-1", onOpenChange);
    expect(toast.error).toHaveBeenCalledWith("Could not load the transaction");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("titles the loading state and never paints the previous row under a new one", async () => {
    detail = base;
    await mount();
    expect(sheetText()).toContain("Anna Petrova");

    getMock.mockImplementationOnce(() => new Promise(() => {}));
    await mount("tx-2");
    expect(sheetText()).not.toContain("Anna Petrova");
    const title = document.querySelector('[data-slot="sheet-title"]');
    expect(title?.textContent).toBe("Loading…");
  });
});
