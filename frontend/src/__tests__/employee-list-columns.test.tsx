// @vitest-environment jsdom
//
// HRP-633 REDO: the Employee role reads a division in the directory schema
// and must still get the Specialization column, between Position and Grade.
// The HR view keeps its seven columns, Specialization once.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import enMessages from "../../messages/en.json";
import { EmployeeList } from "@/components/employees/EmployeeListRow";

const ROW = {
  id: "e-1",
  user_name: "Alice Adams",
  position_title: "Accountant",
  specialization_title: "Payroll",
  grade_title: null,
  division_name: "Finance",
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function columns(hrColumns: boolean): Promise<string[]> {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <EmployeeList employees={[ROW]} testIdPrefix="t" hrColumns={hrColumns} />
      </NextIntlClientProvider>,
    );
  });
  return [...container.querySelectorAll('[role="columnheader"]')].map(
    (el) => el.getAttribute("data-testid")!.replace("t-column-", ""),
  );
}

it("directory view: Position, Specialization, Grade - no HR columns", async () => {
  expect(await columns(false)).toEqual(["name", "position", "specialization", "grade", "division"]);
  expect(container.querySelector('[data-testid="t-e-1-specialization"]')?.textContent).toBe(
    "Payroll",
  );
  expect(container.querySelector('[data-testid="t-e-1-hire-date"]')).toBeNull();
});

it("HR view keeps its seven columns, Specialization once", async () => {
  expect(await columns(true)).toEqual([
    "name",
    "position",
    "specialization",
    "grade",
    "division",
    "status",
    "hire_date",
  ]);
});
