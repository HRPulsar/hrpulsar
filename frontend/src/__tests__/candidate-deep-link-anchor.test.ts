// HRP-494 REDO — the analysis emails deep-link to
// `/recruitment/candidates/{id}?vacancyId={vid}#ai-insights`, and the
// anchor did nothing: the candidate card is fetched after mount, so the
// browser resolves the fragment against the loading placeholder, finds
// no `#ai-insights`, and leaves the reader at the top of the page.
//
// The page can't be mounted under vitest (heavy data deps), so this is
// pinned by source-grep, like the sibling structural suites.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(
  resolve(__dirname, "../app/(dashboard)/recruitment/candidates/[id]/page.tsx"),
  "utf8",
);

const FLAT = SOURCE.replace(/\s+/g, " ");

describe("Candidate page deep-link anchor (HRP-494)", () => {
  it("re-runs the jump itself instead of trusting the native one", () => {
    expect(FLAT).toContain("window.location.hash.slice(1)");
    expect(FLAT).toContain("document.getElementById(anchorId)?.scrollIntoView");
  });

  it("waits for the card before looking for the target", () => {
    // The section only exists once `card` has rendered it.
    expect(FLAT).toContain("if (!card || deepLinkHandled.current) return;");
    expect(FLAT).toMatch(/deepLinkHandled\.current = true;.*\}, \[card\]\);/);
  });

  it("scrolls once per visit, not after every reload of the card", () => {
    // `card` is replaced on every save; a page that yanks itself back to
    // the anchor each time is worse than one that never scrolled.
    expect(FLAT).toContain("const deepLinkHandled = useRef(false);");
  });

  it("honours reduced motion", () => {
    expect(FLAT).toContain('matchMedia?.("(prefers-reduced-motion: reduce)")');
  });
});
