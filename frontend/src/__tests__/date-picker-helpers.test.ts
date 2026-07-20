import { describe, expect, it } from "vitest";

import {
  applyDateMask,
  buildMonthGrid,
  compareIso,
  isSameDay,
  isWithinBounds,
  parseIso,
  startOfMonth,
  toIso,
  yesterdayIso,
} from "@/lib/date-picker-helpers";

describe("date-picker helpers", () => {
  it("toIso pads month and day to two digits", () => {
    expect(toIso(new Date(2024, 0, 5))).toBe("2024-01-05");
    expect(toIso(new Date(2024, 9, 12))).toBe("2024-10-12");
  });

  it("parseIso returns a Date for a well-formed yyyy-mm-dd string", () => {
    const d = parseIso("2024-03-14");
    expect(d).not.toBeNull();
    expect(d?.getFullYear()).toBe(2024);
    expect(d?.getMonth()).toBe(2);
    expect(d?.getDate()).toBe(14);
  });

  it("parseIso returns null for malformed values and impossible dates", () => {
    expect(parseIso("")).toBeNull();
    expect(parseIso("2024-13-01")).toBeNull();
    expect(parseIso("2024-02-30")).toBeNull();
    expect(parseIso("hello")).toBeNull();
    expect(parseIso(undefined)).toBeNull();
    expect(parseIso(null)).toBeNull();
  });

  it("round-trips through toIso/parseIso for arbitrary dates", () => {
    const date = new Date(2026, 5, 1);
    expect(toIso(parseIso(toIso(date))!)).toBe("2026-06-01");
  });

  it("startOfMonth zeroes out the day", () => {
    const d = new Date(2026, 5, 17);
    const s = startOfMonth(d);
    expect(s.getDate()).toBe(1);
    expect(s.getMonth()).toBe(5);
    expect(s.getFullYear()).toBe(2026);
  });

  it("isSameDay compares by calendar fields, not timestamp", () => {
    const a = new Date(2026, 5, 1, 9, 30, 0);
    const b = new Date(2026, 5, 1, 23, 59, 59);
    expect(isSameDay(a, b)).toBe(true);
    expect(isSameDay(a, new Date(2026, 5, 2))).toBe(false);
  });

  it("compareIso orders ISO strings as dates", () => {
    expect(compareIso("2024-01-01", "2024-01-02")).toBe(-1);
    expect(compareIso("2024-01-02", "2024-01-01")).toBe(1);
    expect(compareIso("2024-01-01", "2024-01-01")).toBe(0);
  });

  it("isWithinBounds honours both bounds when provided", () => {
    expect(isWithinBounds("2024-06-01", "2024-01-01", "2024-12-31")).toBe(true);
    expect(isWithinBounds("2024-06-01", "2024-07-01")).toBe(false);
    expect(isWithinBounds("2024-06-01", undefined, "2024-05-31")).toBe(false);
    expect(isWithinBounds("2024-06-01")).toBe(true);
  });

  it("buildMonthGrid returns exactly 42 days, Sunday-first (HRP-152 REDO)", () => {
    // June 2026: 1st is Monday, so the Sunday-first grid back-fills one
    // day (2026-05-31, Sunday).
    const grid = buildMonthGrid(new Date(2026, 5, 1));
    expect(grid).toHaveLength(42);
    expect(toIso(grid[0])).toBe("2026-05-31");
    expect(toIso(grid[1])).toBe("2026-06-01");
    expect(toIso(grid[6])).toBe("2026-06-06");
  });

  it("buildMonthGrid keeps the 1st in column 0 when it is a Sunday", () => {
    // March 2026: 1st is Sunday, so the grid starts exactly on it.
    const grid = buildMonthGrid(new Date(2026, 2, 1));
    expect(toIso(grid[0])).toBe("2026-03-01");
    expect(toIso(grid[6])).toBe("2026-03-07");
  });

  it("yesterdayIso returns yyyy-mm-dd for today - 1", () => {
    const today = new Date(2026, 5, 4);
    expect(yesterdayIso(today)).toBe("2026-06-03");
    const start = new Date(2026, 0, 1);
    expect(yesterdayIso(start)).toBe("2025-12-31");
  });

  it("applyDateMask strips non-digits and inserts dashes (HRP-152 REDO)", () => {
    expect(applyDateMask("")).toBe("");
    expect(applyDateMask("2024")).toBe("2024");
    expect(applyDateMask("20240")).toBe("2024-0");
    expect(applyDateMask("202403")).toBe("2024-03");
    expect(applyDateMask("2024031")).toBe("2024-03-1");
    expect(applyDateMask("20240314")).toBe("2024-03-14");
    // Pre-typed dashes are forgiven; extra digits beyond 8 are dropped.
    expect(applyDateMask("2024-03-14")).toBe("2024-03-14");
    expect(applyDateMask("2024031499")).toBe("2024-03-14");
    // Letters and other junk are stripped without breaking the dash layout.
    expect(applyDateMask("2024abc0314")).toBe("2024-03-14");
  });
});
