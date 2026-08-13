// HRP-507: the DIVERGENCE badge on the vacancy Candidates block gets a
// real hover tooltip (up to 5 competences, then "and N more"), and
// clicking it opens Canvas already filtered to the divergent cells.
//
// Component mounting needs the whole table's data layer, so the contract
// is pinned by source-grep, as with the sibling structural tests.

import { readdirSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const TABLE = readFileSync(
  resolve(__dirname, "../components/recruitment/vacancy-candidates-table.tsx"),
  "utf8",
).replace(/\s+/g, " ");

const CANVAS = readFileSync(
  resolve(
    __dirname,
    "../app/(fullscreen)/recruitment/requisitions/[id]/assessments/canvas/page.tsx",
  ),
  "utf8",
).replace(/\s+/g, " ");

// Catalogs are discovered rather than hardcoded: ru.json is enterprise-only
// and absent from the public repo, where a fixed readFileSync would fail
// collection with ENOENT. Same approach as i18n-catalog-parity.test.ts.
const MESSAGES_DIR = resolve(__dirname, "../../messages");

const CATALOGS: [string, { recruitment: Record<string, string> }][] =
  readdirSync(MESSAGES_DIR)
    .filter((file) => file.endsWith(".json"))
    .sort()
    .map((file) => [
      basename(file, ".json"),
      JSON.parse(readFileSync(resolve(MESSAGES_DIR, file), "utf8")),
    ]);

const EN = CATALOGS.find(([locale]) => locale === "en")![1];

describe("Divergence badge tooltip (HRP-507)", () => {
  it("renders a Tooltip instead of the bare title attribute", () => {
    expect(TABLE).toContain("<TooltipContent");
    expect(TABLE).toContain("-divergence-tooltip`}");
    expect(TABLE).not.toContain("title={tooltipText}");
  });

  it("links into Canvas with the divergences filter applied", () => {
    expect(TABLE).toContain(
      "href={`/recruitment/requisitions/${vacancyId}/canvas?filter=divergences`}",
    );
  });

  it("summarises the competences beyond the previewed five", () => {
    expect(TABLE).toContain("const remaining = count - lines.length;");
    expect(TABLE).toContain(
      '{remaining > 0 && ( <p className="mt-0.5"> {t("candidatesTableDivergenceMore", { count: remaining })}',
    );
  });

  it("tells the user the badge opens Canvas", () => {
    expect(TABLE).toContain('t("candidatesTableDivergenceCanvasHint")');
    expect(EN.recruitment.candidatesTableDivergenceCanvasHint).toBe(
      "Click to view in Canvas",
    );
    for (const [locale, catalog] of CATALOGS) {
      expect(
        catalog.recruitment.candidatesTableDivergenceCanvasHint,
        locale,
      ).toBeTruthy();
    }
  });

  it("keeps the em dash for candidates with no divergence", () => {
    expect(TABLE).toContain("-divergence-empty`}");
  });

  it("makes Canvas honour ?filter=divergences on first render", () => {
    expect(CANVAS).toContain("const searchParams = useSearchParams();");
    expect(CANVAS).toContain(
      'useState( () => searchParams.get("filter") === "divergences", )',
    );
  });
});
