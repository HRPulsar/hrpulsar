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

// HRP-852: the calendar sits on the kit's Base UI popover. Pin the round
// trip a recruiter makes: the icon opens it, a day commits and closes it,
// Escape closes it without a pick.
describe("DatePicker calendar popover (HRP-852)", () => {
  const day = () =>
    document.querySelector('[data-testid="dp-day-2026-08-14"]') as HTMLButtonElement | null;

  async function openCalendar() {
    await act(async () => {
      (container.querySelector('[data-testid="dp-trigger"]') as HTMLButtonElement).click();
    });
  }

  it("opens on the icon, commits a picked day and closes", async () => {
    const { onChange } = renderPicker({ value: "2026-08-01" });
    expect(day()).toBeNull();
    await openCalendar();
    expect(day()).not.toBeNull();
    await act(async () => day()!.click());
    expect(onChange).toHaveBeenCalledWith("2026-08-14");
    await act(async () => {});
    expect(day()).toBeNull();
  });

  it("closes on Escape without picking", async () => {
    const { onChange } = renderPicker({ value: "2026-08-01" });
    await openCalendar();
    expect(day()).not.toBeNull();
    await act(async () => {
      document.activeElement?.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      );
    });
    expect(day()).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });
});
