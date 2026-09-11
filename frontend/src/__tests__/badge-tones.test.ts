import { describe, expect, it } from "vitest";
import { BADGE_COLOR, resolveBadgeColor } from "@/lib/badge-tones";

/**
 * The funnel table paints a stage badge from the stored colour and the
 * stages drawer preselects a swatch for that same value. Both go through
 * this resolver, so an alias it stops honouring would show one colour in
 * the table and another in the editor for the same row.
 */
describe("resolveBadgeColor", () => {
  it("maps the pre-palette seed colours onto neutral", () => {
    for (const legacy of ["slate", "gray", "grey"]) {
      expect(resolveBadgeColor(legacy)).toBe("neutral");
    }
  });

  it("passes a palette key through", () => {
    for (const key of Object.keys(BADGE_COLOR)) {
      expect(resolveBadgeColor(key)).toBe(key);
    }
  });

  it("returns null for a value that names no colour", () => {
    // The field used to accept free text, so stored junk is possible and
    // the caller has to fall back rather than render an undefined class.
    expect(resolveBadgeColor("chartreuse")).toBeNull();
    expect(resolveBadgeColor("")).toBeNull();
    expect(resolveBadgeColor(null)).toBeNull();
    expect(resolveBadgeColor(undefined)).toBeNull();
  });

  it("does not treat Object prototype keys as colours", () => {
    expect(resolveBadgeColor("toString")).toBeNull();
    expect(resolveBadgeColor("constructor")).toBeNull();
  });
});
