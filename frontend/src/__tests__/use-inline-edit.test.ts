import { describe, expect, it, vi } from "vitest";

import { inlineEditKeys } from "@/hooks/use-inline-edit";

// HRP-110: vitest runs without jsdom in this repo, so we don't render the
// hook itself — but the keyboard glue is a pure function and we test it
// directly. State transitions live in `useInlineEdit` and are exercised by
// the two pages that consume it (positions/[id], assessments/[id]); their
// E2E specs cover the integration.

function makeKeyEvent(key: string) {
  const preventDefault = vi.fn();
  return {
    event: { key, preventDefault } as unknown as KeyboardEvent,
    preventDefault,
  };
}

describe("inlineEditKeys", () => {
  it("Enter commits and preventDefaults the keystroke", () => {
    const onCommit = vi.fn();
    const onCancel = vi.fn();
    const handler = inlineEditKeys({ onCommit, onCancel });

    const { event, preventDefault } = makeKeyEvent("Enter");
    handler(event as unknown as React.KeyboardEvent<HTMLInputElement>);

    expect(preventDefault).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("Enter is a no-op while disabled (saving) — guards against double submit", () => {
    const onCommit = vi.fn();
    const onCancel = vi.fn();
    const handler = inlineEditKeys({ onCommit, onCancel, disabled: true });

    const { event, preventDefault } = makeKeyEvent("Enter");
    handler(event as unknown as React.KeyboardEvent<HTMLInputElement>);

    expect(preventDefault).toHaveBeenCalledTimes(1);
    expect(onCommit).not.toHaveBeenCalled();
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("Escape cancels and does not preventDefault", () => {
    const onCommit = vi.fn();
    const onCancel = vi.fn();
    const handler = inlineEditKeys({ onCommit, onCancel });

    const { event, preventDefault } = makeKeyEvent("Escape");
    handler(event as unknown as React.KeyboardEvent<HTMLInputElement>);

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onCommit).not.toHaveBeenCalled();
    expect(preventDefault).not.toHaveBeenCalled();
  });

  it("other keys are ignored", () => {
    const onCommit = vi.fn();
    const onCancel = vi.fn();
    const handler = inlineEditKeys({ onCommit, onCancel });

    const { event, preventDefault } = makeKeyEvent("Tab");
    handler(event as unknown as React.KeyboardEvent<HTMLInputElement>);

    expect(onCommit).not.toHaveBeenCalled();
    expect(onCancel).not.toHaveBeenCalled();
    expect(preventDefault).not.toHaveBeenCalled();
  });
});
