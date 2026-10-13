// HRP-854: a failed decomposition or skill row names its cause with a
// code; the UI renders the code in the reader's locale and falls back to
// the stored en message only on rows from before the codes existed.

import { describe, expect, it } from "vitest";

import enMessages from "../../messages/en.json";
import { generationErrorText } from "@/components/coverage/generation-errors";

const coverage = enMessages.coverage as Record<string, string>;
const t = (key: string) => coverage[key];

describe("generationErrorText", () => {
  it("renders a known code from the catalog, not the stored en message", () => {
    expect(
      generationErrorText(t, "credits_limit_reached", "Action unavailable...", "skillFailed"),
    ).toBe(coverage.genErrorCredits);
    expect(generationErrorText(t, "reaped_stuck", null, "generationFailed")).toBe(
      coverage.genErrorNotFinished,
    );
    // Session codes that name a real cause render their own sentence - the
    // old banner appended the stored en text for these (review fix).
    expect(generationErrorText(t, "overload", "en text", "generationFailed")).toBe(
      coverage.genErrorOverload,
    );
    expect(generationErrorText(t, "insufficient_data", "en text", "generationFailed")).toBe(
      coverage.genErrorInsufficientData,
    );
    expect(generationErrorText(t, "parse_error", "en text", "generationFailed")).toBe(
      coverage.genErrorParse,
    );
  });

  it("reads an unknown code as the surface's generic failure", () => {
    expect(generationErrorText(t, "service_error", "TypeError", "skillFailed")).toBe(
      coverage.skillFailed,
    );
  });

  it("falls back to the stored text on a row without a code", () => {
    expect(generationErrorText(t, null, "Legacy English text", "skillFailed")).toBe(
      "Legacy English text",
    );
    expect(generationErrorText(t, null, null, "skillFailed")).toBe(coverage.skillFailed);
  });

  it("has a catalog entry behind every mapped code", () => {
    for (const key of [
      "genErrorCredits",
      "genErrorDemoQuota",
      "genErrorNoProcessor",
      "genErrorModelUnavailable",
      "genErrorTruncated",
      "genErrorOverload",
      "genErrorInsufficientData",
      "genErrorParse",
      "genErrorNotFinished",
      "genErrorNotApplicable",
      "genErrorPackUnavailable",
    ]) {
      expect(coverage[key], key).toBeTruthy();
    }
  });
});
