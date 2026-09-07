// HRP-672: the catalogue table and the position detail page label the same
// `positions.source` column. They used to spell the relation out separately
// and disagreed on `ai_draft` — the table calling it Manual, the detail page
// AI. Both now route through one resolver; this pins all three values so the
// next screen to render the column cannot reintroduce the split.
import { describe, expect, it } from "vitest";

import { positionSourceLabel } from "@/app/(dashboard)/company/positions/source-label";

// The wording lives in the `company` namespace; only the key matters here.
const t = (key: string) => key;

describe("position source labels", () => {
  it("calls a hand-made position manual", () => {
    expect(positionSourceLabel(t, "manual")).toBe("sourceManual");
  });

  it("calls an approved AI position AI", () => {
    expect(positionSourceLabel(t, "ai_approved")).toBe("sourceAi");
  });

  it("calls an AI draft AI on every screen", () => {
    // Reachable on the detail page: the catalogue filters drafts into their
    // own section, a direct link does not.
    expect(positionSourceLabel(t, "ai_draft")).toBe("sourceAi");
  });

  it("shows an unknown source as its raw code instead of calling it AI", () => {
    // A value the resolver has never heard of must not be dressed up as
    // one of the two it knows.
    expect(positionSourceLabel(t, "imported")).toBe("imported");
  });
});
