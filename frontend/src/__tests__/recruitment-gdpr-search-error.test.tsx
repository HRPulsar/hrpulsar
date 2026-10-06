// @vitest-environment jsdom
//
// Review 05.10 (E11): a failed candidate search on the GDPR page shows the
// error, not "no candidates found" — which would read as "no data held".

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

const getMock = vi.fn(() =>
  Promise.reject(new Error("Search is unavailable")),
);

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api: { get: getMock },
}));

vi.mock("@/components/recruitment", () => ({
  RecruitmentBreadcrumbs: () => null,
  RecruitmentTabs: () => null,
}));

const page = await import("@/app/(dashboard)/recruitment/gdpr/page");

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("GDPR candidate search", () => {
  it("shows the error when the search fails", async () => {
    await act(async () => {
      root.render(
        <NextIntlClientProvider locale="en" messages={enMessages}>
          <page.default />
        </NextIntlClientProvider>,
      );
    });
    const input = container.querySelector<HTMLInputElement>(
      '[data-testid="recruitment-gdpr-search-input"]',
    )!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!;
      setter.call(input, "anna");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      container
        .querySelector("form")!
        .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    expect(getMock).toHaveBeenCalled();
    expect(
      container.querySelector('[data-testid="recruitment-gdpr-search-error"]')
        ?.textContent,
    ).toBe("Search is unavailable");
    expect(
      container.querySelector('[data-testid="recruitment-gdpr-no-results"]'),
    ).toBeNull();
  });
});
