// HRP-427 / HRP-836 / HRP-785: the vacancy status model on screen.
//
// * kebab commands per status, between Edit and Archive, in ticket order;
// * every command confirms first; Close asks for a resolution and checks it
//   against the funnel;
// * the read-only matrix mirrors the backend's VACANCY_LOCKED_SURFACES and
//   reaches every block it names;
// * the Funnel block shows a Conversion column and the overall conversion.

import { readdirSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  VACANCY_COMMAND_TARGET,
  VACANCY_READ_ONLY_SURFACES,
  VACANCY_STATUS_COMMANDS,
  vacancyLocks,
  vacancyResolutionLabel,
} from "@/lib/vacancy-status";

const read = (rel: string) => readFileSync(resolve(__dirname, rel), "utf8");
const flat = (rel: string) => read(rel).replace(/\s+/g, " ");

const MENU = flat(
  "../app/(dashboard)/recruitment/requisitions/_components/VacancyActionsMenu.tsx",
);
const DIALOG = flat(
  "../app/(dashboard)/recruitment/requisitions/_components/VacancyStatusDialog.tsx",
);
const LIST = flat("../app/(dashboard)/recruitment/requisitions/page.tsx");
const DETAIL = flat("../app/(dashboard)/recruitment/requisitions/[id]/page.tsx");
const CANDIDATE = flat("../app/(dashboard)/recruitment/candidates/[id]/page.tsx");
const INTERVIEW = flat("../app/(dashboard)/recruitment/interviews/[id]/page.tsx");
const AI_INSIGHTS = flat("../components/recruitment/ai-insights-section.tsx");
const QUESTIONS = flat("../components/recruitment/interview-question-sets.tsx");
const INTERVIEWS = flat("../components/recruitment/candidate-interviews-section.tsx");
const ROUNDS = flat("../components/recruitment/manager-assessment-section.tsx");
const ANALYTICS = flat("../components/recruitment/vacancy-analytics-tab.tsx");

// ru.json is enterprise-only: discover the catalogs instead of naming them.
const MESSAGES_DIR = resolve(__dirname, "../../messages");
const CATALOGS: [string, { recruitment: Record<string, string> }][] =
  readdirSync(MESSAGES_DIR)
    .filter((file) => file.endsWith(".json"))
    .map((file) => [
      basename(file, ".json"),
      JSON.parse(readFileSync(resolve(MESSAGES_DIR, file), "utf8")),
    ]);

describe("kebab commands (HRP-427 / HRP-836)", () => {
  it("lists the lifecycle commands per status in ticket order", () => {
    expect(VACANCY_STATUS_COMMANDS).toEqual({
      draft: ["publish"],
      open: ["pause", "close", "cancel"],
      paused: ["reopen", "close", "cancel"],
    });
    expect(VACANCY_COMMAND_TARGET).toEqual({
      publish: "open",
      pause: "paused",
      reopen: "open",
      cancel: "cancelled",
    });
  });

  it("renders Edit, then the commands, then Archive", () => {
    const edit = MENU.indexOf("vacancy-actions-menu-edit-");
    const commands = MENU.indexOf("vacancy-actions-menu-${cmd}-");
    const archive = MENU.indexOf("vacancy-actions-menu-archive-");
    expect(edit).toBeGreaterThan(-1);
    expect(edit).toBeLessThan(commands);
    expect(commands).toBeLessThan(archive);
  });

  it("drops Edit on a closed or cancelled vacancy", () => {
    expect(MENU).toContain(
      'const canEdit = !isArchived && !vacancyLocks(vacancy.status, "vacancy");',
    );
    expect(MENU).toContain("{canEdit && ( <DropdownMenuItem");
  });
});

describe("confirmation dialog", () => {
  it("posts Close to /close and every other command to /status", () => {
    expect(DIALOG).toContain("`/recruitment/vacancies/${vacancy.id}/close`");
    expect(DIALOG).toContain("`/recruitment/vacancies/${vacancy.id}/status`");
    expect(DIALOG).toContain("status: VACANCY_COMMAND_TARGET[command]");
  });

  it("offers the two resolutions and checks them against the funnel", () => {
    expect(DIALOG).toContain('{ value: "hired", labelKey: "vacancyResolutionHired" }');
    expect(DIALOG).toContain(
      '{ value: "closed_no_hire", labelKey: "vacancyResolutionNoHire" }',
    );
    expect(DIALOG).toContain(
      'resolution === "hired" && hiredCount === 0 ? t("vacancyCloseNeedsHire")',
    );
    expect(DIALOG).toContain(
      'resolution === "closed_no_hire" && hiredCount > 0 ? t("vacancyCloseHasHire")',
    );
    expect(DIALOG).toContain(
      '(command === "close" && (!resolution || !!resolutionError))',
    );
  });

  it("labels the resolution next to the status", () => {
    const t = (key: string) => key;
    expect(vacancyResolutionLabel(t, "hired")).toBe("vacancyResolutionHired");
    expect(vacancyResolutionLabel(t, "closed_no_hire")).toBe(
      "vacancyResolutionNoHire",
    );
    expect(vacancyResolutionLabel(t, "cancelled")).toBeNull();
    expect(LIST).toContain("vacancy-list-row-${vacancy.id}-resolution");
    expect(DETAIL).toContain('data-testid="vacancy-detail-resolution"');
  });
});

describe("read-only by vacancy status (HRP-836)", () => {
  it("mirrors the backend matrix", () => {
    const ended = [
      "vacancy",
      "ai_insights",
      "questions",
      "interviews",
      "manager_assessments",
    ];
    expect(VACANCY_READ_ONLY_SURFACES).toEqual({
      paused: ["questions", "interviews", "manager_assessments"],
      closed: ended,
      cancelled: ended,
    });
    expect(vacancyLocks("paused", "ai_insights")).toBe(false);
    expect(vacancyLocks("paused", "interviews")).toBe(true);
    expect(vacancyLocks("open", "interviews")).toBe(false);
    expect(vacancyLocks(undefined, "vacancy")).toBe(false);
  });

  it("reaches every block of the candidate card, per vacancy", () => {
    expect(CANDIDATE).toContain(
      'read_only: vacancyLocks(a.vacancy_status, "manager_assessments")',
    );
    expect(CANDIDATE).toContain(
      'questions_read_only: vacancyLocks(a.vacancy_status, "questions")',
    );
    expect(CANDIDATE).toContain(
      'interviews_read_only: vacancyLocks(a.vacancy_status, "interviews")',
    );
    expect(QUESTIONS).toContain(
      "const canEvaluate = canEvaluateCandidates && !currentVacancy?.questions_read_only;",
    );
    expect(INTERVIEWS).toContain(
      'const canEdit = canManageSection("recruitment") && !currentVacancy?.interviews_read_only;',
    );
    expect(ROUNDS).toContain(
      "const canRunRounds = canRunHiringRounds && !activeVacancy?.read_only;",
    );
    expect(AI_INSIGHTS).toContain('"ai_insights", );');
    expect(AI_INSIGHTS).toContain("!resumeAvailable || statusReadOnly");
  });

  it("freezes the interview page and the vacancy page", () => {
    expect(INTERVIEW).toContain(
      'const statusLocked = vacancyLocks(cvCtx?.vacancy_status, "interviews");',
    );
    expect(INTERVIEW).toContain("const canEdit = canManage && !statusLocked;");
    // Both pages say why the controls are gone.
    expect(INTERVIEW).toContain(
      'data-testid="recruitment-interview-vacancy-readonly-banner"',
    );
    expect(DETAIL).toContain('data-testid="vacancy-status-readonly-banner"');
    expect(DETAIL).toContain(
      'const statusReadOnly = vacancyLocks(vacancy.status, "vacancy");',
    );
    expect(DETAIL).toContain(
      'canManageSection("recruitment") && !vacancy.archived_at && !statusReadOnly;',
    );
  });

  it("re-reads a draft vacancy once its first candidate lands (HRP-427)", () => {
    expect(DETAIL).toContain(
      'if (n > 0 && vacancy.status === "draft") void loadVacancy();',
    );
  });
});

describe("funnel conversion (HRP-785)", () => {
  it("shows a Conversion column, the overall value and the formula hint", () => {
    expect(ANALYTICS).toContain(
      "data-testid={`recruitment-vacancy-analytics-conversion-${stage.stage_id}`}",
    );
    expect(ANALYTICS).toContain("formatPercent(t, stage.conversion_percent)");
    expect(ANALYTICS).toContain(
      'data-testid="recruitment-vacancy-analytics-overall-conversion"',
    );
    expect(ANALYTICS).toContain("value: formatPercent(t, data.overall_conversion_percent)");
    expect(ANALYTICS).toContain('text={t("analyticsTabConversionHint")}');
    expect(ANALYTICS).toContain(
      'return value == null ? EM_DASH : t("analyticsTabPercent", { value });',
    );
  });
});

describe("catalogs", () => {
  const keys = [
    "actionPublish",
    "actionPause",
    "actionReopen",
    "actionCloseVacancy",
    "actionCancelVacancy",
    "vacancyPublishTitle",
    "vacancyPublishDescription",
    "vacancyPauseTitle",
    "vacancyPauseDescription",
    "vacancyReopenTitle",
    "vacancyReopenDescription",
    "vacancyCloseTitle",
    "vacancyCloseDescription",
    "vacancyCloseConfirm",
    "vacancyCancelTitle",
    "vacancyCancelDescription",
    "vacancyCancelConfirm",
    "vacancyCloseResolutionLabel",
    "vacancyResolutionHired",
    "vacancyResolutionNoHire",
    "vacancyCloseNeedsHire",
    "vacancyCloseHasHire",
    "vacancyToastPublished",
    "vacancyToastPaused",
    "vacancyToastReopened",
    "vacancyToastClosed",
    "vacancyToastCancelled",
    "vacancyStatusChangeFailed",
    "analyticsTabConversion",
    "analyticsTabOverallConversion",
    "analyticsTabPercent",
    "analyticsTabConversionHint",
    "vacancyStatusReadOnlyBanner",
    "interviewVacancyReadOnlyBanner",
  ];

  it.each(CATALOGS)("%s carries every new key", (_locale, catalog) => {
    for (const key of keys) {
      expect(catalog.recruitment[key], key).toBeTruthy();
    }
  });
});
