"use client";

import { useCallback, useEffect, useRef } from "react";
import { api } from "@/lib/api";
import { deriveSalaryForSelection } from "@/lib/vacancy-salary";
import type {
  SalaryFormValues,
  SpecializationGradeRow,
} from "@/lib/vacancy-salary";

/**
 * HRP-440: one Salary range recompute for every vacancy surface — Create,
 * the Edit page and the inline edit of the Overview block.
 *
 * The returned callback is fired from the Position / Specializations /
 * Grades change handlers, never from an effect keyed on the form values.
 * That distinction is the whole fix: an effect also runs when Edit loads a
 * saved vacancy into the form, so it needed a guard against overwriting
 * the stored range — and that guard then blocked the recompute QA asked
 * for. Wired to the handlers, "the user picked something" and "the form
 * was populated" are no longer the same event, so an explicit pick can
 * overwrite the range unconditionally while simply opening Edit leaves it
 * untouched. A range typed by hand survives until the next such pick.
 */
export function useSalaryAutofill(
  apply: (derived: SalaryFormValues) => void,
): (specializationIds: string[], gradeIds: string[]) => void {
  const applyRef = useRef(apply);
  useEffect(() => {
    applyRef.current = apply;
  });
  const latest = useRef(0);

  return useCallback((specializationIds: string[], gradeIds: string[]) => {
    // Each pick invalidates the answer still in flight for the previous
    // one, so a slow response cannot land on top of a newer selection.
    const ticket = ++latest.current;
    void (async () => {
      const derived = await deriveSalaryForSelection(
        specializationIds,
        gradeIds,
        (specializationId) =>
          api.get<SpecializationGradeRow[]>(
            `/specializations/${specializationId}/grades`,
          ),
      );
      if (ticket !== latest.current || !derived) return;
      applyRef.current(derived);
    })();
  }, []);
}
