// @vitest-environment jsdom
//
// HRP-335: the DatePicker replaced native `<input type="date">` across
// Assessments / Development / Exams / Talent Market. E2E specs (and
// Playwright's `fill()`) type a full ISO string into the input and then
// blur by clicking elsewhere — pin that commit path plus the min-bound
// revert so the swap can't silently break form state.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import { DatePicker } from "@/components/ui/date-picker";

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

function renderPicker(props: Partial<React.ComponentProps<typeof DatePicker>>) {
  const onChange = vi.fn();
  act(() => {
    root.render(
      // HRP-482: the picker's Clear button reads common.* via t()
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <DatePicker
          value={props.value ?? ""}
          onChange={props.onChange ?? onChange}
          data-testid="dp"
          {...props}
        />
      </NextIntlClientProvider>,
    );
  });
  const input = container.querySelector(
    '[data-testid="dp"]',
  ) as HTMLInputElement;
  return { input, onChange };
}

function typeAndBlur(input: HTMLInputElement, value: string) {
  act(() => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  act(() => {
    input.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
  });
}

describe("DatePicker (HRP-335 commit semantics)", () => {
  it("commits a full ISO string on blur (Playwright fill() path)", () => {
    const { input, onChange } = renderPicker({});
    typeAndBlur(input, "2026-08-01");
    expect(onChange).toHaveBeenCalledWith("2026-08-01");
  });

  it("reverts an out-of-bounds date instead of committing it", () => {
    const { input, onChange } = renderPicker({ min: "2026-01-01" });
    typeAndBlur(input, "2025-12-31");
    expect(onChange).not.toHaveBeenCalled();
    expect(input.value).toBe("");
  });

  it("commits on Enter without waiting for blur", () => {
    const { input, onChange } = renderPicker({});
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!;
      setter.call(input, "2026-09-15");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    act(() => {
      input.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
      );
    });
    expect(onChange).toHaveBeenCalledWith("2026-09-15");
  });

  it("clears the value on empty blur when clearable", () => {
    const { input, onChange } = renderPicker({ value: "2026-08-01" });
    typeAndBlur(input, "");
    expect(onChange).toHaveBeenCalledWith("");
  });
});
