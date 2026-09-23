// @vitest-environment jsdom
//
// HRP-866 (W6-10) - the agent setup guide of the Coverage tab: the steps an
// agent takes, folded by agent type and ordered by the hours behind them.
// No step for an agent - no section; no ready skill - the download is
// disabled and says why.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { CoverageStep } from "@/lib/api/work";

vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { downloadAgentBundle: vi.fn(), registerAgent: vi.fn() },
}));
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { AgentGuide, BUNDLE_FILE_NAME, agentGroups } = await import(
  "@/components/coverage/agent-guide"
);
const { workApi } = await import("@/lib/api/work");

function step(position: number, pack: string | null, patch: Partial<CoverageStep> = {}): CoverageStep {
  return {
    step_id: `s-${position}`,
    position,
    title: `Step ${position}`,
    state: "accepted",
    codes: [],
    required_codes: [],
    in_scope: true,
    mode: "automatable",
    quality: "strong",
    verdict: "agent",
    agent: pack
      ? { pack_id: `pack-${pack}`, pack_code: pack, agent_id: null, agent_name: null }
      : null,
    human: null,
    human_backup: false,
    accountable: null,
    needs_accountable: false,
    gap_label: null,
    hours_per_year: null,
    hire_need: null,
    skill_status: "none",
    tentative: false,
    review_human_share: null,
    ...patch,
  };
}

describe("agentGroups", () => {
  it("counts the hours a group frees, not what its checker keeps", () => {
    // HRP-858: the same figure as the summary's "frees up" - a reviewed
    // step hands over only what its checker does not keep.
    const groups = agentGroups([
      step(1, "drafting", { hours_per_year: 100, mode: "review_required", review_human_share: 30 }),
    ]);
    expect(groups[0].hours).toBe(70);
  });

  it("folds the steps by agent type, largest yearly hours first", () => {
    const groups = agentGroups([
      step(3, "extraction", { hours_per_year: 50, mode: "review_required", skill_status: "ready" }),
      step(1, "extraction", { hours_per_year: 100 }),
      step(2, "drafting", { hours_per_year: 300, mode: "draft_then_review" }),
      step(4, "coordinator"),
    ]);

    expect(groups.map((g) => g.packCode)).toEqual(["drafting", "extraction", "coordinator"]);
    const extraction = groups[1];
    expect(extraction.steps.map((s) => s.position)).toEqual([1, 3]);
    expect(extraction.hours).toBe(150);
    expect(extraction.ready).toBe(1);
    expect(extraction.packId).toBe("pack-extraction");
    // No estimate is no hours, not a missing group.
    expect(groups[2].hours).toBe(0);
  });

  it("settles a tie in hours by the first step", () => {
    const groups = agentGroups([
      step(5, "drafting", { hours_per_year: 10 }),
      step(2, "extraction", { hours_per_year: 10 }),
    ]);
    expect(groups.map((g) => g.packCode)).toEqual(["extraction", "drafting"]);
  });

  it("leaves out what no agent takes", () => {
    expect(
      agentGroups([
        // A person the company named outranks the agent that could.
        step(1, "extraction", { verdict: "human", hours_per_year: 500 }),
        // Stays with people: outside the two agent buckets.
        step(2, "extraction", { mode: "blocked_judgment", hours_per_year: 500 }),
        step(3, null, { verdict: "gap" }),
        step(4, null, { verdict: "out_of_scope", mode: null, in_scope: false }),
      ]),
    ).toEqual([]);
  });

  it("names every registered agent of the type once", () => {
    const named = (position: number, name: string) =>
      step(position, "extraction", {
        agent: { pack_id: "p", pack_code: "extraction", agent_id: `a-${name}`, agent_name: name },
      });
    const [group] = agentGroups([named(1, "Claude Code"), named(2, "Claude Code"), named(3, "Cursor")]);
    expect(group.agentNames).toEqual(["Claude Code", "Cursor"]);
  });
});

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.mocked(workApi.downloadAgentBundle).mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const onSkill = vi.fn();

async function render(steps: CoverageStep[], props: { canEdit?: boolean; canRegisterAgent?: boolean } = {}) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <AgentGuide
          containerId="c-1"
          steps={steps}
          canEdit={props.canEdit ?? true}
          canRegisterAgent={props.canRegisterAgent ?? true}
          packLabel={(code) => `pack:${code}`}
          onSkill={onSkill}
          onChanged={() => {}}
        />
      </NextIntlClientProvider>,
    );
  });
}

const byId = (id: string) => container.querySelector(`[data-testid="${id}"]`) as HTMLElement | null;

describe("AgentGuide", () => {
  it("is absent when no step is an agent's", async () => {
    await render([step(1, null, { verdict: "gap" })]);
    expect(byId("coverage-guide")).toBeNull();
  });

  it("counts the agent types and lists them by hours", async () => {
    await render([
      step(1, "extraction", { hours_per_year: 1200 }),
      step(2, "drafting", { hours_per_year: 3000.4 }),
    ]);

    expect(byId("coverage-guide-title")!.textContent).toBe("This work needs 2 agent types");
    const groups = [...container.querySelectorAll('[data-testid^="coverage-guide-group-"]')]
      .map((el) => el.getAttribute("data-testid"))
      .filter((id) => /group-[a-z_]+$/.test(id!));
    expect(groups).toEqual([
      "coverage-guide-group-drafting",
      "coverage-guide-group-extraction",
    ]);
    expect(byId("coverage-guide-group-drafting")!.textContent).toContain("pack:drafting");
    expect(byId("coverage-guide-group-drafting-hours")!.textContent).toBe("≈ 3,000 h/year");
  });

  it("says hours are not estimated rather than showing zero", async () => {
    await render([step(1, "extraction")]);
    expect(byId("coverage-guide-group-extraction-hours")!.textContent).toBe(
      enMessages.coverage.agentGuideHoursUnknown,
    );
  });

  it("keeps the download disabled, with the reason in sight, until a skill is ready", async () => {
    await render([step(1, "extraction")]);

    expect((byId("coverage-guide-download") as HTMLButtonElement).disabled).toBe(true);
    expect(byId("coverage-guide-download-hint")!.textContent).toBe(
      enMessages.coverage.agentGuideDownloadEmpty,
    );
    expect(byId("coverage-guide-group-extraction-skills")!.textContent).toBe(
      "Skills ready: 0 of 1",
    );
  });

  it("downloads the bundle under its file name once a skill is ready", async () => {
    vi.mocked(workApi.downloadAgentBundle).mockResolvedValue(new Blob(["zip"]));
    const createObjectURL = vi.fn(() => "blob:bundle");
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() });
    const saved: string[] = [];
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        saved.push(this.download);
      });
    await render([step(1, "extraction", { skill_status: "ready" })]);

    const button = byId("coverage-guide-download") as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    await act(async () => button.click());

    expect(workApi.downloadAgentBundle).toHaveBeenCalledWith("c-1");
    expect(saved).toEqual([BUNDLE_FILE_NAME]);
    click.mockRestore();
  });

  it("opens the step's own skill dialog - the existing generation, not a second one", async () => {
    const target = step(1, "extraction");
    await render([target]);

    await act(async () => byId("coverage-guide-skill-s-1")!.click());

    expect(onSkill).toHaveBeenCalledWith(target);
  });

  it("offers the registration only where no agent is registered and the viewer may", async () => {
    const registered = step(2, "drafting", {
      agent: { pack_id: "p-d", pack_code: "drafting", agent_id: "a-1", agent_name: "Claude Code" },
    });
    await render([step(1, "extraction"), registered]);

    expect(byId("coverage-guide-group-extraction-use-agent")).not.toBeNull();
    expect(byId("coverage-guide-group-drafting-use-agent")).toBeNull();
    expect(byId("coverage-guide-group-drafting-agent")!.textContent).toBe("Agent: Claude Code");

    await render([step(1, "extraction"), registered], { canRegisterAgent: false });
    expect(byId("coverage-guide-group-extraction-use-agent")).toBeNull();
  });

  it("lets a reader open a ready skill but not start a generation", async () => {
    await render(
      [step(1, "extraction"), step(2, "extraction", { skill_status: "ready" })],
      { canEdit: false },
    );

    expect((byId("coverage-guide-skill-s-1") as HTMLButtonElement).disabled).toBe(true);
    expect(byId("coverage-guide-skill-s-1")!.title).toBe(enMessages.coverage.skillReadOnlyHint);
    expect((byId("coverage-guide-skill-s-2") as HTMLButtonElement).disabled).toBe(false);
  });
});
