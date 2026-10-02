// HRP-417 — archived vacancies used to sit in the default list ("All
// statuses" folded them in, HRP-363). They are now hidden until the
// "Show archived (N)" toggle is on; N comes from the list response so it
// follows the same status filter the rows do.

import { readdirSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const PAGE = readFileSync(
  resolve(__dirname, "../app/(dashboard)/recruitment/requisitions/page.tsx"),
  "utf8",
).replace(/\s+/g, " ");

const MESSAGES_DIR = resolve(__dirname, "../../messages");
const CATALOGS: [string, { recruitment: Record<string, string> }][] =
  readdirSync(MESSAGES_DIR)
    .filter((file) => file.endsWith(".json"))
    .sort()
    .map((file) => [
      basename(file, ".json"),
      JSON.parse(readFileSync(resolve(MESSAGES_DIR, file), "utf8")),
    ]);

describe("Vacancy list hides archived rows by default (HRP-417)", () => {
  it("asks the API to exclude archived rows unless the toggle is on", () => {
    expect(PAGE).toContain(
      'params.set("archived", showArchived ? "include" : "exclude");',
    );
    expect(PAGE).not.toContain('params.set("archived", "include");');
    // The dedicated Archived view is untouched.
    expect(PAGE).toContain('params.set("archived", "only");');
  });

  it("shows the toggle with the server-side count, outside the Archived view", () => {
    expect(PAGE).toContain('data-testid="recruitment-vacancies-show-archived"');
    expect(PAGE).toContain("setArchivedCount(data.archived_count ?? 0);");
    expect(PAGE).toContain('t("vacanciesShowArchived", { count: archivedCount })');
    expect(PAGE).toMatch(/\{!isArchivedView && \( <label/);
  });

  it("carries the toggle label with its count in every catalog", () => {
    expect(CATALOGS.map(([locale]) => locale)).toEqual(
      expect.arrayContaining(["de", "en"]),
    );
    for (const [locale, catalog] of CATALOGS) {
      expect(catalog.recruitment.vacanciesShowArchived, locale).toContain("{count}");
    }
  });
});
