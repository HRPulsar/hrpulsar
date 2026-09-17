// 2.0.0 review §3 — two helpers of the Steps tab.
//
// `hoursOutOfRange` keeps a number the backend answers with 422 on every
// blur inside the browser; `mergeReordered` keeps the answer of a PATCH
// that landed while the reorder request was in flight.

import { expect, it } from "vitest";

import { hoursOutOfRange } from "@/components/coverage/hours-fields";
import { mergeReordered } from "@/components/coverage/steps-editor";
import type { WorkStep } from "@/lib/api/work";

const STEP: WorkStep = {
  id: "s-1",
  container_id: "c-1",
  position: 1,
  title: "Draft the offer",
  description: null,
  responsibility: "none",
  reversibility: null,
  hours_per_run: null,
  runs_per_year: null,
  output_type: "draft",
  state: "system_suggested",
  gap_label: null,
  notes: null,
  executor_employee_id: null,
  accountable_employee_id: null,
  primitive_codes: [],
  capabilities: [],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

it("accepts an empty, a typical and a boundary estimate", () => {
  expect(hoursOutOfRange({ hours: "", runs: "" })).toBe(false);
  expect(hoursOutOfRange({ hours: "0.5", runs: "50" })).toBe(false);
  // The backend's own bounds: 0.01 h and one run a year are legal.
  expect(hoursOutOfRange({ hours: "0.01", runs: "1" })).toBe(false);
  expect(hoursOutOfRange({ hours: "200", runs: "1000000" })).toBe(false);
});

it("refuses a number the backend would refuse", () => {
  expect(hoursOutOfRange({ hours: "0", runs: "" })).toBe(true);
  expect(hoursOutOfRange({ hours: "201", runs: "" })).toBe(true);
  expect(hoursOutOfRange({ hours: "", runs: "0" })).toBe(true);
  expect(hoursOutOfRange({ hours: "", runs: "1000001" })).toBe(true);
  expect(hoursOutOfRange({ hours: "-1", runs: "" })).toBe(true);
});

it("takes the order from the server and the fields from the state", () => {
  const local = [
    { ...STEP, id: "a", position: 1, title: "Edited while dragging" },
    { ...STEP, id: "b", position: 2, title: "B" },
  ];
  // What the reorder answered with: the same rows, swapped, and with the
  // title as it was before the concurrent PATCH.
  const fresh = [
    { ...STEP, id: "b", position: 1, title: "B" },
    { ...STEP, id: "a", position: 2, title: "Stale title" },
  ];

  expect(mergeReordered(local, fresh).map((s) => [s.id, s.position, s.title])).toEqual([
    ["b", 1, "B"],
    ["a", 2, "Edited while dragging"],
  ]);
});

it("keeps a row the state has never seen", () => {
  const fresh = [{ ...STEP, id: "new", position: 1, title: "Added elsewhere" }];
  expect(mergeReordered([], fresh)).toEqual(fresh);
});
