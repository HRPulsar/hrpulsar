// HRP-152: every date in the UI renders ISO `yyyy-MM-dd` (English calendar,
// English placeholder). The helper is the single choke point — tests pin
// the format so a future refactor can't sneak `ru-RU` / `dd.mm.yyyy` back in.

import { describe, expect, it } from "vitest";
import {
  DATE_PLACEHOLDER,
  formatDate,
  formatDateOnlyIso,
  formatDateTime,
} from "@/lib/date-format";

describe("DATE_PLACEHOLDER", () => {
  it("is the lowercase ISO placeholder shown in date inputs", () => {
    expect(DATE_PLACEHOLDER).toBe("yyyy-mm-dd");
  });
});

describe("formatDate", () => {
  it("returns date-only ISO input verbatim so a UTC-midnight Date can't roll the day back", () => {
    expect(formatDate("2026-05-22")).toBe("2026-05-22");
    expect(formatDate("2026-01-01")).toBe("2026-01-01");
  });

  it("formats a Date instance as yyyy-MM-dd using local time", () => {
    expect(formatDate(new Date(2026, 0, 5))).toBe("2026-01-05");
    expect(formatDate(new Date(2026, 11, 31))).toBe("2026-12-31");
  });

  it("zero-pads single-digit month and day", () => {
    expect(formatDate(new Date(2026, 2, 9))).toBe("2026-03-09");
  });

  it("returns the empty string for null / undefined / empty input", () => {
    expect(formatDate(null)).toBe("");
    expect(formatDate(undefined)).toBe("");
    expect(formatDate("")).toBe("");
  });

  it("uses the fallback when given an unparseable value", () => {
    expect(formatDate("not a date", "—")).toBe("—");
    expect(formatDate(null, "—")).toBe("—");
  });
});

describe("formatDateTime", () => {
  it("formats a Date as yyyy-MM-dd HH:mm using local time", () => {
    expect(formatDateTime(new Date(2026, 4, 22, 9, 5))).toBe("2026-05-22 09:05");
    expect(formatDateTime(new Date(2026, 4, 22, 23, 59))).toBe("2026-05-22 23:59");
  });

  it("returns the empty string for null / undefined", () => {
    expect(formatDateTime(null)).toBe("");
    expect(formatDateTime(undefined)).toBe("");
  });

  it("uses the fallback when given an unparseable value", () => {
    expect(formatDateTime("garbage", "—")).toBe("—");
  });
});

describe("formatDateOnlyIso", () => {
  it("passes through a clean ISO date-only string", () => {
    expect(formatDateOnlyIso("2026-05-22")).toBe("2026-05-22");
  });

  it("slices a leading ISO date out of a full datetime string", () => {
    expect(formatDateOnlyIso("2026-05-22T13:45:00Z")).toBe("2026-05-22");
  });

  it("returns the fallback when the prefix doesn't match yyyy-mm-dd", () => {
    expect(formatDateOnlyIso("22.05.2026", "—")).toBe("—");
    expect(formatDateOnlyIso(null, "—")).toBe("—");
    expect(formatDateOnlyIso("", "—")).toBe("—");
  });
});
