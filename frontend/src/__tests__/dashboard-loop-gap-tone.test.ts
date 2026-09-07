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
const DYNAMICS = { days: 90, plans_completed: 0, competences_improved: 0 };
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
    dynamics: DYNAMICS,
    data_version: "v1",
  };
}

function gapTone(stages: ReturnType<typeof buildStages>) {
  return stages.find((s) => s.key === "gaps")?.tone;
}

function companyStages(employees: number, withoutPlan: number, dynamics = DYNAMICS) {
  return buildStages(devLoopStages(employees, withoutPlan), dynamics, t);
}

describe("company loop hero: the gaps tile", () => {
  it("goes red only while some gap has no plan", () => {
    expect(gapTone(companyStages(3, 2))).toBe("attention");
  });

  it("stays out of the red once every gap owner has a plan", () => {
    expect(gapTone(companyStages(3, 0))).not.toBe("attention");
  });

  it("is untinted when there are no gaps at all", () => {
    expect(gapTone(companyStages(0, 0))).toBeUndefined();
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
      "hintMyStageDynamics",
    ]);
  });
});

// HRP-724: the dynamics tile is not a loop stage — it reports what moved in
// a window the reader picks, so it names its own testid and only lights up
// when something actually moved.

describe("the dynamics tile", () => {
  const moved = { days: 30, plans_completed: 2, competences_improved: 5 };
  // The value carries a unit, so it is built from a plural message rather
  // than a bare String(): echo the arguments to keep the assertion about
  // the number and not just the key.
  const tArgs = (key: string, values?: Record<string, string | number>) =>
    values ? `${key}:${JSON.stringify(values)}` : key;

  function dynamicsTile(stages: ReturnType<typeof buildStages>) {
    return stages.find((s) => s.key === "dynamics");
  }

  it("reports finished plans on both heroes under a stable testid", () => {
    const company = buildStages(devLoopStages(0, 0), moved, tArgs);
    expect(dynamicsTile(company)).toMatchObject({
      value: 'stageDynamicsValue:{"count":2}',
      testid: "dashboard-loop-dynamics",
      tone: "positive",
    });
    const mine = buildMyStages(
      { ...myLoop(0, false), dynamics: moved },
      tArgs,
      formatDate,
    );
    expect(dynamicsTile(mine)).toMatchObject({
      value: 'stageDynamicsValue:{"count":2}',
      testid: "dashboard-my-dynamics",
      tone: "positive",
    });
  });

  it("drops the unassessed chip once everyone has been assessed", () => {
    // HRP-730: the badge is a task ("assess 2"), so at zero there is no task
    // and no chip — not a chip reading "0".
    const someLeft = buildStages(devLoopStages(3, 2), DYNAMICS, tArgs);
    expect(someLeft.find((s) => s.key === "assessed")?.badge).toBe(
      'stageAssessedNoAssessment:{"count":2}',
    );
    const allDone = buildStages(
      {
        ...devLoopStages(3, 2),
        assessed: { covered: 10, total_active: 10, percent: 100 },
      },
      DYNAMICS,
      tArgs,
    );
    expect(allDone.find((s) => s.key === "assessed")?.badge).toBeUndefined();
  });

  it("stays untinted when nothing moved in the window", () => {
    expect(dynamicsTile(companyStages(3, 2))?.tone).toBeUndefined();
    expect(
      dynamicsTile(buildMyStages(myLoop(2, false), t, formatDate))?.tone,
    ).toBeUndefined();
  });
});
