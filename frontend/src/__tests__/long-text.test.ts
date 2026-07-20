import { describe, expect, it } from "vitest";

import { LONG_TEXT_THRESHOLD, trimLongText } from "@/lib/long-text";

// HRP-319: vacancy Overview block clips Description / Requirements /
// Responsibilities / Conditions / Main tasks / Additional tasks / KPI at
// 300 chars and exposes a Show more / Show less toggle. The trim helper is
// shared between all seven fields; regressing it would silently bring back the
// old "only Description is truncated" behaviour.

describe("trimLongText", () => {
  it("returns the original text untouched when below threshold", () => {
    const text = "Short description";
    expect(trimLongText(text, false)).toEqual({ visible: text, isLong: false });
    expect(trimLongText(text, true)).toEqual({ visible: text, isLong: false });
  });

  it("treats exactly threshold characters as not long", () => {
    const text = "a".repeat(LONG_TEXT_THRESHOLD);
    expect(trimLongText(text, false).isLong).toBe(false);
    expect(trimLongText(text, false).visible).toBe(text);
  });

  it("flags strictly above threshold as long", () => {
    const text = "a".repeat(LONG_TEXT_THRESHOLD + 1);
    expect(trimLongText(text, false).isLong).toBe(true);
  });

  it("truncates collapsed long text to threshold + ellipsis", () => {
    const text = "x".repeat(LONG_TEXT_THRESHOLD + 50);
    const result = trimLongText(text, false);
    expect(result.visible).toHaveLength(LONG_TEXT_THRESHOLD + 1);
    expect(result.visible.endsWith("…")).toBe(true);
    expect(result.visible.slice(0, LONG_TEXT_THRESHOLD)).toBe(
      text.slice(0, LONG_TEXT_THRESHOLD),
    );
  });

  it("returns the full text when expanded, regardless of length", () => {
    const text = "y".repeat(LONG_TEXT_THRESHOLD + 200);
    const result = trimLongText(text, true);
    expect(result.visible).toBe(text);
    expect(result.isLong).toBe(true);
  });

  it("accepts a custom threshold", () => {
    const result = trimLongText("hello world", false, 5);
    expect(result.isLong).toBe(true);
    expect(result.visible).toBe("hello…");
  });
});
