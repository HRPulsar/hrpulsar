// @vitest-environment jsdom
//
// HRP-1084 review: the requisites dialog reopened after a save starts from
// what is stored now, not from what it loaded the first time - otherwise a
// second Save would put the old requisites back.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { BillingRequisites } from "@/lib/types";

const get = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { get, put: vi.fn() },
  ApiError: class extends Error {},
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { RequisitesDialog } = await import("@/components/billing/requisites-form");

const CONFIG = {
  buyer_fields: [{ key: "legal_name", required: true, pattern: null, multiline: false }],
};
const stored = (legal_name: string): BillingRequisites => ({
  legal_name,
  legal_address: "",
  country: null,
  fields: {},
});

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
  vi.clearAllMocks();
});

async function render(open: boolean) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <RequisitesDialog open={open} onOpenChange={() => {}} onSaved={() => {}} />
      </NextIntlClientProvider>,
    );
  });
}

const legalName = () =>
  document.querySelector<HTMLInputElement>(
    '[data-testid="settings-billing-requisites-dialog-legal-name"]',
  )?.value;

describe("RequisitesDialog", () => {
  it("reads the requisites afresh on every open", async () => {
    let name = "Before GmbH";
    get.mockImplementation(async (path: string) =>
      path === "/billing/invoice-config" ? CONFIG : stored(name),
    );

    await render(true);
    expect(legalName()).toBe("Before GmbH");

    await render(false);
    name = "After GmbH"; // saved meanwhile, here or by the purchase flow
    await render(true);
    expect(legalName()).toBe("After GmbH");
  });
});
