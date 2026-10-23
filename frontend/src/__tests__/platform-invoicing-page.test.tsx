// @vitest-environment jsdom
//
// HRP-1084 review: on the platform invoicing page an image upload keeps what
// is typed in the issuer card, and an empty VAT rate is refused instead of
// going out as 0%.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { PlatformInvoicingSettings } from "@/lib/api-platform";

const getInvoicing = vi.fn();
const updateInvoicing = vi.fn();
const uploadInvoicingImage = vi.fn();

vi.mock("@/lib/api-platform", () => ({
  platformApi: { getInvoicing, updateInvoicing, uploadInvoicingImage },
}));

const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: toastError } }));

const { default: InvoicingPage } = await import(
  "@/app/(platform)/platform/invoicing/page"
);

const SETTINGS: PlatformInvoicingSettings = {
  billing_operator_email: null,
  scheme: "de",
  supplier: { name: "Acme GmbH" },
  vat_mode: "standard",
  vat_rate: 0.19,
  number_prefix: "RE",
  timezone: "Europe/Berlin",
  document_locale: "de",
  wording: {},
  images: {},
  generation_enabled: true,
  schemes: [
    {
      code: "de",
      supplier_fields: [{ key: "name", required: true, pattern: null, multiline: false }],
      vat_modes: ["standard"],
      default_vat_rate: 0.19,
      defaults: { number_prefix: "RE", timezone: "Europe/Berlin", document_locale: "de" },
      wording_defaults: { de: {}, en: {} },
    },
  ],
};

let container: HTMLDivElement;
let root: Root;

beforeEach(async () => {
  getInvoicing.mockResolvedValue(SETTINGS);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <InvoicingPage />
      </NextIntlClientProvider>,
    );
  });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.clearAllMocks();
});

const byTestId = <T extends Element>(id: string) =>
  container.querySelector(`[data-testid="${id}"]`) as T;

async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(
      input,
      value,
    );
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

describe("platform invoicing page", () => {
  it("keeps the issuer draft when an image is uploaded", async () => {
    uploadInvoicingImage.mockResolvedValue({ ...SETTINGS, images: { logo: true } });
    await type(byTestId("platform-invoicing-supplier-name"), "Acme Typed");

    const file = new File(["png"], "logo.png", { type: "image/png" });
    const input = byTestId<HTMLInputElement>("platform-invoicing-image-logo-input");
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    await act(async () => {
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });

    expect(uploadInvoicingImage).toHaveBeenCalledWith("logo", file);
    expect(byTestId<HTMLInputElement>("platform-invoicing-supplier-name").value).toBe(
      "Acme Typed",
    );
  });

  it("refuses an empty VAT rate instead of saving 0%", async () => {
    await type(byTestId("platform-invoicing-vat-rate"), "");
    await act(async () => {
      byTestId<HTMLButtonElement>("platform-invoicing-issuer-save").click();
    });
    expect(updateInvoicing).not.toHaveBeenCalled();
    expect(toastError).toHaveBeenCalledWith(enMessages.platform.invoicingVatRateInvalid);
  });

  it("sends a typed rate as a fraction", async () => {
    updateInvoicing.mockResolvedValue(SETTINGS);
    await type(byTestId("platform-invoicing-vat-rate"), "7");
    await act(async () => {
      byTestId<HTMLButtonElement>("platform-invoicing-issuer-save").click();
    });
    expect(updateInvoicing).toHaveBeenCalledWith(expect.objectContaining({ vat_rate: 0.07 }));
  });
});
