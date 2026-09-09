// HRP-667 REDO task 2 — once a vacancy has a card on the internal talent
// market, "Allow internal search for this vacancy" is on and stays on.
// Turning it off there froze the shortlist and left it on screen, so the
// requisition displayed internal candidates it claimed not to search for.
//
// The checkbox is rendered on and disabled with the reason underneath;
// the backend refuses the same change with 422
// (`vacancy_internal_search_locked_by_card`) so the invariant does not
// depend on the form — see
// backend/tests/unit/test_hrp663_internal_candidates.py.
//
// The form pulls its own dictionaries on mount and cannot be mounted
// here, so this is pinned by source-grep like the sibling structural
// suites.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import enMessages from "../../messages/en.json";
import deMessages from "../../messages/de.json";
import ruMessages from "../../messages/ru.json";

const flat = (path: string) =>
  readFileSync(resolve(__dirname, path), "utf8").replace(/\s+/g, " ");

const FORM = flat("../app/(dashboard)/recruitment/requisitions/_components/VacancyForm.tsx");
const EDIT = flat("../app/(dashboard)/recruitment/requisitions/[id]/edit/page.tsx");
const NEW = flat("../app/(dashboard)/recruitment/requisitions/new/page.tsx");

describe("Internal search switch lock (HRP-667)", () => {
  it("forces the checkbox on and disabled while the vacancy is posted", () => {
    expect(FORM).toContain(
      "checked={internalSearchLocked || values.internal_search_allowed}",
    );
    expect(FORM).toContain("disabled={disabled || internalSearchLocked}");
  });

  it("explains the lock under the checkbox", () => {
    expect(FORM).toContain(
      'internalSearchLocked ? t("vacancyInternalSearchLockedHint") : t("vacancyInternalSearchHint")',
    );
  });

  it("carries the explanation in all three catalogues", () => {
    expect(enMessages.recruitment.vacancyInternalSearchLockedHint).toBeTruthy();
    expect(deMessages.recruitment.vacancyInternalSearchLockedHint).toBeTruthy();
    expect(ruMessages.recruitment.vacancyInternalSearchLockedHint).toBeTruthy();
  });

  it("locks from the live link the vacancy page reads, not a stale id", () => {
    // `talent_card_id` in this payload is null once the card is deleted
    // from the talent market, which is exactly when the backend stops
    // refusing the change.
    expect(EDIT).toContain(
      "`/recruitment/vacancies/${id}/internal-candidates`",
    );
    expect(EDIT).toContain("locked = internal.talent_card_id !== null;");
    expect(EDIT).toContain("setInternalSearchLocked(locked);");
    expect(EDIT).toContain("internalSearchLocked={internalSearchLocked}");
  });

  it("seeds the form with the value the locked checkbox shows", () => {
    // A vacancy posted before the rule existed can be sitting on the wrong
    // side of it. The box renders on either way, so the form has to carry
    // the same value — otherwise Save sends the stale false straight back
    // and the row never heals.
    expect(EDIT).toContain("values.internal_search_allowed = true;");
    // Seeded before the baseline is taken, or the page opens dirty.
    expect(EDIT.indexOf("values.internal_search_allowed = true;")).toBeLessThan(
      EDIT.indexOf("initialRef.current = values;"),
    );
  });

  it("leaves the create form alone — a new vacancy has no card", () => {
    expect(NEW).not.toContain("internalSearchLocked");
  });
});
