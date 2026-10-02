// HRP-917 — after a status change the success toast read "Status changed
// to on_review": the detail page passed the wire code straight into the
// message while every other surface (badge, filters, Change status modal)
// already went through assessmentStatusLabel. Both entry points named in
// the ticket — the list's Change status modal and the detail page's
// Details buttons — now render the translated label.

import { readdirSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  ASSESSMENT_STATUS_OPTIONS,
  assessmentStatusLabel,
} from "@/lib/assessment-status";

const src = (path: string) =>
  readFileSync(resolve(__dirname, path), "utf8").replace(/\s+/g, " ");

const DETAIL = src("../app/(dashboard)/assessments/[id]/page.tsx");
const LIST = src("../app/(dashboard)/assessments/page.tsx");

// Catalogs are discovered, not imported by name: ru.json is enterprise-only
// and missing from the public repo.
const MESSAGES_DIR = resolve(__dirname, "../../messages");
const CATALOGS: [string, { assessments: Record<string, string> }][] =
  readdirSync(MESSAGES_DIR)
    .filter((file) => file.endsWith(".json"))
    .sort()
    .map((file) => [
      basename(file, ".json"),
      JSON.parse(readFileSync(resolve(MESSAGES_DIR, file), "utf8")),
    ]);

describe("Status change toast names the status in the UI language (HRP-917)", () => {
  it("translates the status on the detail page toast", () => {
    expect(DETAIL).toContain(
      't("toastStatusChanged", { status: assessmentStatusLabel(t, status) })',
    );
    expect(DETAIL).not.toContain('t("toastStatusChanged", { status })');
  });

  it("translates the status on the list page Change status toast", () => {
    expect(LIST).toContain(
      't("toastStatusChanged", { status: assessmentStatusLabel(t, newStatus) })',
    );
    expect(LIST).not.toContain('t("toastStatusUpdated")');
  });

  it("has a translated label for every status in every catalog", () => {
    expect(CATALOGS.map(([locale]) => locale)).toEqual(
      expect.arrayContaining(["de", "en"]),
    );
    for (const [locale, catalog] of CATALOGS) {
      const t = (key: string) => catalog.assessments[key];
      expect(catalog.assessments.toastStatusChanged, locale).toContain("{status}");
      for (const code of ASSESSMENT_STATUS_OPTIONS) {
        const label = assessmentStatusLabel(t, code);
        expect(label, `${locale}:${code}`).toBeTruthy();
        // The fallback returns the wire code itself — that is the bug.
        expect(label, `${locale}:${code}`).not.toBe(code);
      }
    }
  });
});
