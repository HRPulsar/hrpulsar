// @vitest-environment jsdom
//
// HRP-1105 - the levels window on the employee card coloured 75% green with
// its own copy of the thresholds. It now asks the shared scale, so a level
// at the bar is yellow, as every other competence percent is.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";

import enMessages from "../../messages/en.json";
import { EmployeeCompetenceBreakdown } from "@/components/employees/employee-competence-breakdown";
import { BADGE_COLOR } from "@/lib/badge-tones";

it("colours each level on the shared scale against the row's bar", async () => {
  const breakdown = [75, 76, 50, 49, 65].map((percent, i) => ({
    skill_level_id: `l${i}`,
    skill_level_title: `Level ${i}`,
    skill_level_sort_index: i,
    percent,
  }));
  const open = async (bar: number) => {
    const root = createRoot(document.body.appendChild(document.createElement("div")));
    await act(async () => {
      root.render(
        <NextIntlClientProvider locale="en" messages={enMessages}>
          <EmployeeCompetenceBreakdown
            competenceId="c"
            competenceTitle="Communication"
            breakdown={breakdown}
            bar={bar}
            testIdPrefix={`p${bar}`}
          />
        </NextIntlClientProvider>,
      );
    });
    await act(async () => {
      document.querySelector<HTMLElement>(`[data-testid="p${bar}-info-c"]`)!.click();
    });
  };
  const chip = (bar: number, id: string) =>
    document.querySelector(`[data-testid="p${bar}-breakdown-row-${id}"] span`)!.className;

  await open(75);
  expect(chip(75, "l0")).toContain(BADGE_COLOR.yellow);
  expect(chip(75, "l1")).toContain(BADGE_COLOR.green);
  expect(chip(75, "l2")).toContain(BADGE_COLOR.yellow);
  expect(chip(75, "l3")).toContain(BADGE_COLOR.red);

  // A row with its own bar judges its levels by it, like the row's chip.
  await open(60);
  expect(chip(60, "l4")).toContain(BADGE_COLOR.green);
});
