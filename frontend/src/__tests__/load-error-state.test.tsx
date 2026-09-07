// @vitest-environment jsdom
//
// HRP-728: an API failure on a list page used to render as the empty state
// ("no records yet"). Every list now shares one error block with a retry;
// pin its message, its testids and that a retry in flight ignores clicks.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import { LoadErrorState } from "@/components/load-error-state";

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

function renderState(props: { onRetry: () => void; retrying?: boolean }) {
  act(() => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <LoadErrorState testIdPrefix="things" {...props} />
      </NextIntlClientProvider>,
    );
  });
  const button = container.querySelector<HTMLButtonElement>(
    '[data-testid="things-load-retry"]',
  );
  if (!button) throw new Error("retry button did not render");
  return button;
}

describe("LoadErrorState (HRP-728)", () => {
  it("renders the shared message under the page's testid prefix", () => {
    renderState({ onRetry: () => {} });
    const block = container.querySelector('[data-testid="things-load-failed"]');
    expect(block?.textContent).toContain("Could not load data.");
    expect(block?.textContent).toContain("Try again");
  });

  it("calls onRetry on click", () => {
    const onRetry = vi.fn();
    const button = renderState({ onRetry });
    act(() => button.click());
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("ignores clicks while a retry is in flight", () => {
    const onRetry = vi.fn();
    const button = renderState({ onRetry, retrying: true });
    expect(button.disabled).toBe(true);
    act(() => button.click());
    expect(onRetry).not.toHaveBeenCalled();
  });
});
