import { describe, expect, it } from "vitest";

import { buildMyStages, buildStages } from "@/app/(dashboard)/dashboard/page";

// HRP-656: on both loop heroes red means "nobody owns this". A gap that an
// open development plan already covers is the loop doing its job and gets
// amber, not an alarm. The manager hero got the rule at the time; the
// personal one kept painting every gap red, which is why it is pinned here
// alongside. The personal condition must stay the mirror of the backend's
// `gap_without_plan` finding (analytics/service.py), which fires only when
// there is no open PDP.

const t = (key: string) => key;
const formatDate = (iso: string) => iso;

function devLoopStages(employees: number, withoutPlan: number) {
  return {
    assessed: { covered: 8, total_active: 10, percent: 80 },
    gaps: { employees, competences: employees * 2, without_plan: withoutPlan },
    developing: { open_pdps: 1, gap_employees_with_plan: 1 },
    closed: { gaps_closed_90d: 0, plans_done_on_time_90d: 0 },
  };
}

function myLoop(competences: number, hasPlan: boolean) {
  return {
    stages: {
      assessed: { finished_at: null, avg_percent: null },
      gaps: {
        competences,
        items: Array.from({ length: competences }, (_, i) => ({
          competence_id: `competence-${i}`,
          title: `Competence ${i}`,
          percent: 40,
        })),
      },
      developing: {
        pdp: hasPlan
          ? {
              id: "pdp-1",
              title: "Growth plan",
              status: "in_progress",
              progress: 30,
              deadline: null,
            }
          : null,
      },
      closed: { gaps_closed_90d: 0 },
    },
    findings: [],
    strengths: { top: [], rare_skills: [] },
    growth: null,
    history: [],
    data_version: "v1",
  };
}

function gapTone(stages: ReturnType<typeof buildStages>) {
  return stages.find((s) => s.key === "gaps")?.tone;
}

describe("company loop hero: the gaps tile", () => {
  it("goes red only while some gap has no plan", () => {
    expect(gapTone(buildStages(devLoopStages(3, 2), t))).toBe("attention");
  });

  it("stays out of the red once every gap owner has a plan", () => {
    expect(gapTone(buildStages(devLoopStages(3, 0), t))).not.toBe("attention");
  });

  it("is untinted when there are no gaps at all", () => {
    expect(gapTone(buildStages(devLoopStages(0, 0), t))).toBeUndefined();
  });
});

describe("personal loop hero: the gaps tile", () => {
  it("goes red when gaps have no active plan", () => {
    const stages = buildMyStages(myLoop(2, false), t, formatDate);
    expect(gapTone(stages)).toBe("attention");
  });

  it("stays out of the red while a plan is open on them", () => {
    const stages = buildMyStages(myLoop(2, true), t, formatDate);
    expect(gapTone(stages)).not.toBe("attention");
  });

  it("is untinted when there are no gaps at all", () => {
    const stages = buildMyStages(myLoop(0, false), t, formatDate);
    expect(gapTone(stages)).toBeUndefined();
  });
});

describe("personal loop hero: hints", () => {
  it("explains every stage, the way the company hero does", () => {
    const stages = buildMyStages(myLoop(1, true), t, formatDate);
    expect(stages.map((s) => s.hint)).toEqual([
      "hintMyStageAssessed",
      "hintMyStageGaps",
      "hintMyStageDeveloping",
      "hintMyStageClosed",
    ]);
  });
});
