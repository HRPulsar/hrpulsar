// @vitest-environment jsdom
//
// HRP-659: the dashboard explains its numbers through a question-mark hint
// instead of renaming the agreed labels. Touch devices have no hover, so
// the click toggle is the part that must not regress — pin it together with
// the accessible name and the button type (a bare <button> inside a form
// would submit it).

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Hint } from "@/components/ui/hint";
import { TooltipProvider } from "@/components/ui/tooltip";

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

function renderHint() {
  act(() => {
    root.render(
      <TooltipProvider>
        <Hint text="What this counts" title="Closed" data-testid="hint" />
      </TooltipProvider>,
    );
  });
  const button = container.querySelector<HTMLButtonElement>(
    '[data-testid="hint"]',
  );
  if (!button) throw new Error("hint trigger did not render");
  return button;
}

describe("Hint (HRP-659)", () => {
  it("renders an accessible, non-submitting trigger", () => {
    const button = renderHint();
    expect(button.tagName).toBe("BUTTON");
    expect(button.type).toBe("button");
    expect(button.getAttribute("aria-label")).toBe(
      "Closed. What this counts",
    );
  });

  it("opens the tooltip on click and closes it on the next click", () => {
    const button = renderHint();
    expect(document.body.textContent).not.toContain("What this counts");

    act(() => button.click());
    expect(document.body.textContent).toContain("What this counts");

    act(() => button.click());
    expect(document.body.textContent).not.toContain("What this counts");
  });
});
