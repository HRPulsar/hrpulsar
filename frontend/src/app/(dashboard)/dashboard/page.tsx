"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useFormatter, useTranslations } from "next-intl";
import {
  AlertTriangle,
  ArrowRight,
  Clock,
  Info,
  Loader2,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/context/auth-context";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { dictionaryItemLabel } from "@/lib/reference-labels";
import type { AssessmentList, Tenant } from "@/lib/types";

interface OnboardingStatus {
  needs_onboarding: boolean;
}

/** Loose shape of the next-intl translator so plain helpers below can take it
 * as an argument instead of being turned into components. */
type Translate = (
  key: string,
  values?: Record<string, string | number>,
) => string;

// --- Development loop (GET /analytics/dev-loop) ---

interface DevLoopStages {
  assessed: { covered: number; total_active: number; percent: number };
  gaps: { employees: number; competences: number };
  developing: { open_pdps: number; gap_employees_with_plan: number };
  closed: { gaps_closed_90d: number; plans_done_on_time_90d: number };
}

interface DevLoopFindingEmployee {
  id: string;
  name: string;
  division: string | null;
}

interface DevLoopFinding {
  code: string;
  severity: "alert" | "warn" | "info";
  count: number;
  employees: DevLoopFindingEmployee[];
  href: string;
}

interface DevLoop {
  stages: DevLoopStages;
  findings: DevLoopFinding[];
  data_version: string;
}

interface AiSummary {
  summary: string;
  cached: boolean;
  data_version: string;
}

// --- Personal loop (GET /analytics/my-loop) ---

interface DictItem {
  id: string;
  type: string;
  title: string;
  i18n_key: string | null;
}

interface MyCompetence {
  competence_id: string;
  title: string;
  percent: number | null;
}

interface MyLoop {
  stages: {
    assessed: { finished_at: string | null; avg_percent: number | null };
    gaps: { competences: number; items: MyCompetence[] };
    developing: {
      pdp: {
        id: string;
        title: string;
        status: string;
        progress: number;
        deadline: string | null;
      } | null;
    };
    closed: { gaps_closed_90d: number };
  };
  findings: { code: string; severity: "alert" | "warn" | "info"; count: number; href: string }[];
  strengths: { top: MyCompetence[]; rare_skills: MyCompetence[] };
  growth: {
    current_grade: DictItem | null;
    specialization: DictItem | null;
    next_grade: DictItem | null;
    missing: MyCompetence[];
  } | null;
  history: { finished_at: string; avg_percent: number }[];
  data_version: string;
}

// --- Development loop hero ---

function Sparkline({ values }: { values: number[] }) {
  const w = 100;
  const h = 28;
  if (values.length < 2) {
    return <svg width={w} height={h} className="text-accent" />;
  }
  const max = Math.max(...values);
  const min = Math.min(...values);
  const span = max - min || 1;
  const pts = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * w;
      const y = h - ((v - min) / span) * (h - 2) - 1;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg width={w} height={h} className="text-accent" aria-hidden>
      <polyline
        points={pts}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

interface LoopStageSpec {
  key: string;
  href: string;
  value: string;
  sub: string;
  attention?: boolean;
  positive?: boolean;
  badge?: number;
  /** 0–100 → renders a thin progress bar under the value. */
  progress?: number;
  /** ≥2 points → renders a sparkline next to the value. */
  series?: number[];
}

function buildStages(stages: DevLoopStages, t: Translate): LoopStageSpec[] {
  return [
    {
      key: "assessed",
      href: "/assessments",
      value: `${stages.assessed.percent}%`,
      sub: t("stageAssessedSub", {
        covered: stages.assessed.covered,
        total: stages.assessed.total_active,
      }),
      progress: stages.assessed.percent,
    },
    {
      key: "gaps",
      href: "/employees",
      value: String(stages.gaps.employees),
      sub: t("stageGapsSub", { count: stages.gaps.competences }),
      attention: stages.gaps.employees > 0,
      badge: stages.gaps.competences > 0 ? stages.gaps.competences : undefined,
    },
    {
      key: "developing",
      href: "/development",
      value: String(stages.developing.open_pdps),
      sub: t("stageDevelopingSub", {
        count: stages.developing.gap_employees_with_plan,
      }),
      progress:
        stages.gaps.employees > 0
          ? Math.min(
              100,
              Math.round(
                (stages.developing.gap_employees_with_plan /
                  stages.gaps.employees) *
                  100,
              ),
            )
          : undefined,
    },
    {
      key: "closed",
      href: "/development",
      value: String(stages.closed.gaps_closed_90d),
      sub: t("stageClosedSub", { count: stages.closed.plans_done_on_time_90d }),
      positive: stages.closed.gaps_closed_90d > 0,
    },
  ];
}

function StagesHero({
  title,
  subtitle,
  stages,
  testidPrefix,
}: {
  title: string;
  subtitle: string;
  stages: LoopStageSpec[];
  testidPrefix: string;
}) {
  const t = useTranslations("dashboard");
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card ring-1 ring-foreground/5">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h3 className="text-sm font-semibold">{title}</h3>
        <span className="text-[11.5px] text-muted-foreground">{subtitle}</span>
      </div>
      <div className="grid grid-cols-2 lg:flex">
        {stages.map((stage, i) => (
          <div key={stage.key} className="flex flex-1 items-stretch min-w-0">
            <Link
              href={stage.href}
              data-testid={`${testidPrefix}-${stage.key}`}
              className="group flex-1 min-w-0 p-4 transition-colors hover:bg-muted/60"
            >
              <div className="text-[11.5px] font-medium uppercase tracking-wide text-muted-foreground">
                {t(`stage_${stage.key}`)}
              </div>
              <div className="mt-2 flex items-baseline justify-between gap-1.5">
                <span className="flex items-baseline gap-1.5">
                  <span
                    className={cn(
                      "text-[26px] font-bold leading-none tracking-[-0.025em]",
                      stage.attention && "text-red-600 dark:text-red-400",
                      stage.positive && "text-emerald-600 dark:text-emerald-400",
                    )}
                  >
                    {stage.value}
                  </span>
                  {stage.badge !== undefined && (
                    <span className="rounded-full bg-red-500/10 px-1.5 py-0.5 text-[11px] font-semibold text-red-700 dark:text-red-400">
                      {stage.badge}
                    </span>
                  )}
                </span>
                {stage.series && stage.series.length > 1 && (
                  <Sparkline values={stage.series} />
                )}
              </div>
              <div className="mt-1 truncate text-[11px] text-muted-foreground">
                {stage.sub}
              </div>
              {stage.progress !== undefined && (
                <div className="mt-2 h-1 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-accent"
                    style={{ width: `${stage.progress}%` }}
                  />
                </div>
              )}
            </Link>
            {i < stages.length - 1 && (
              <div className="hidden items-center px-1 text-muted-foreground/40 lg:flex">
                <ArrowRight className="h-4 w-4" />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function DevLoopHero({ loop }: { loop: DevLoop }) {
  const t = useTranslations("dashboard");
  return (
    <StagesHero
      title={t("loopTitle")}
      subtitle={t("loopSubtitle")}
      stages={buildStages(loop.stages, t)}
      testidPrefix="dashboard-loop-stage"
    />
  );
}

// --- Action queue ---

const SEVERITY_STYLES: Record<DevLoopFinding["severity"], string> = {
  alert: "bg-red-500/10 text-red-700 dark:text-red-400",
  warn: "bg-amber-500/10 text-amber-700 dark:text-amber-400",
  info: "bg-accent/10 text-accent",
};

function SeverityIcon({ severity }: { severity: DevLoopFinding["severity"] }) {
  if (severity === "alert") return <AlertTriangle className="h-3.5 w-3.5" />;
  if (severity === "warn") return <Clock className="h-3.5 w-3.5" />;
  return <Info className="h-3.5 w-3.5" />;
}

function findingSubline(finding: DevLoopFinding, t: Translate): string | null {
  if (finding.employees.length === 0) return null;
  const names = finding.employees.map((e) => e.name).join(", ");
  const rest = finding.count - finding.employees.length;
  return rest > 0 ? `${names} ${t("andMore", { count: rest })}` : names;
}

type AiState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "done"; text: string }
  | { status: "error"; message?: string };

// The daily-cap 429 carries a localized explanation — surfacing the
// generic "try again" for it would invite the user to keep burning the
// counter with retries that can only fail until tomorrow.
function aiErrorState(err: unknown): AiState {
  return {
    status: "error",
    message:
      err instanceof ApiError && err.status === 429 ? err.message : undefined,
  };
}

function ActionQueue({
  findings,
  dataVersion,
}: {
  findings: DevLoopFinding[];
  dataVersion: string;
}) {
  const t = useTranslations("dashboard");
  const [ai, setAi] = useState<AiState>({ status: "idle" });

  async function explain() {
    setAi({ status: "loading" });
    try {
      // data_version lets a cache hit on the backend skip re-aggregating
      // the loop — and pins the summary to the state on screen.
      const res = await api.post<AiSummary>("/analytics/dev-loop/ai-summary", {
        data_version: dataVersion,
      });
      setAi({ status: "done", text: res.summary });
    } catch (err) {
      setAi(aiErrorState(err));
    }
  }

  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-border bg-card ring-1 ring-foreground/5">
      <div className="flex items-center justify-between gap-2 border-b border-border p-4">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold">{t("queueTitle")}</h3>
          <span className="rounded-full bg-accent/10 px-1.5 py-0.5 text-[11px] font-semibold text-accent">
            {t("queueCount", { count: findings.length })}
          </span>
        </div>
        {ai.status !== "done" && (
          <Button
            size="sm"
            variant="ghost"
            className="text-accent hover:text-accent"
            disabled={ai.status === "loading"}
            onClick={explain}
            data-testid="dashboard-ai-summary-btn"
          >
            {ai.status === "loading" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            {ai.status === "loading" ? t("aiExplaining") : t("aiExplain")}
          </Button>
        )}
      </div>
      {ai.status === "error" && (
        <div className="border-b border-border bg-red-500/5 px-4 py-2 text-[12px] text-red-700 dark:text-red-400">
          {ai.message ?? t("aiSummaryFailed")}
        </div>
      )}
      {ai.status === "done" && (
        <div
          className="flex gap-2.5 border-b border-border bg-accent/5 px-4 py-3"
          data-testid="dashboard-ai-summary-panel"
        >
          <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-accent">
              {t("aiSummaryTitle")}
            </div>
            <p className="mt-1 text-[13px] leading-relaxed">{ai.text}</p>
          </div>
        </div>
      )}
      {findings.length === 0 ? (
        <div className="p-8 text-center text-sm text-muted-foreground">
          {t("queueEmpty")}
        </div>
      ) : (
        <ul className="divide-y divide-border">
          {findings.map((finding) => {
            const subline = findingSubline(finding, t);
            return (
              <li
                key={finding.code}
                className="flex items-center gap-3 px-4 py-3"
                data-testid={`dashboard-action-${finding.code}`}
              >
                <span
                  className={cn(
                    "flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
                    SEVERITY_STYLES[finding.severity],
                  )}
                >
                  <SeverityIcon severity={finding.severity} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-medium">
                    {t(`finding_${finding.code}`, { count: finding.count })}
                  </div>
                  {subline && (
                    <div className="mt-0.5 truncate text-[11.5px] text-muted-foreground">
                      {subline}
                    </div>
                  )}
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  render={<Link href={finding.href} />}
                  data-testid="dashboard-action-cta"
                >
                  {t(`findingCta_${finding.code}`)}
                </Button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// --- Personal dashboard (employee view) ---

function buildMyStages(
  loop: MyLoop,
  t: Translate,
  formatDate: (iso: string) => string,
): LoopStageSpec[] {
  const { assessed, gaps, developing, closed } = loop.stages;
  const pdp = developing.pdp;
  return [
    {
      key: "assessed",
      href: "/assessments",
      value: assessed.avg_percent !== null ? `${assessed.avg_percent}%` : "—",
      sub:
        assessed.finished_at !== null
          ? t("myStageAssessedSub", { date: formatDate(assessed.finished_at) })
          : t("myStageAssessedEmpty"),
      series: loop.history.map((h) => h.avg_percent),
    },
    {
      key: "gaps",
      href: "/development",
      value: String(gaps.competences),
      sub:
        gaps.competences > 0
          ? gaps.items.map((g) => g.title).join(", ")
          : t("myStageGapsEmpty"),
      attention: gaps.competences > 0,
    },
    {
      key: "developing",
      href: "/development",
      value: pdp ? `${pdp.progress}%` : "—",
      sub: pdp ? pdp.title : t("myStageNoPlan"),
      progress: pdp ? pdp.progress : undefined,
    },
    {
      key: "closed",
      href: "/development",
      value: String(closed.gaps_closed_90d),
      sub: t("myStageClosedSub"),
      positive: closed.gaps_closed_90d > 0,
    },
  ];
}

function MyActionQueue({
  findings,
  dataVersion,
}: {
  findings: MyLoop["findings"];
  dataVersion: string;
}) {
  const t = useTranslations("dashboard");
  const [ai, setAi] = useState<AiState>({ status: "idle" });

  async function explain() {
    setAi({ status: "loading" });
    try {
      const res = await api.post<AiSummary>("/analytics/my-loop/ai-summary", {
        data_version: dataVersion,
      });
      setAi({ status: "done", text: res.summary });
    } catch (err) {
      setAi(aiErrorState(err));
    }
  }

  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-border bg-card ring-1 ring-foreground/5">
      <div className="flex items-center justify-between gap-2 border-b border-border p-4">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold">{t("myQueueTitle")}</h3>
          <span className="rounded-full bg-accent/10 px-1.5 py-0.5 text-[11px] font-semibold text-accent">
            {t("queueCount", { count: findings.length })}
          </span>
        </div>
        {ai.status !== "done" && (
          <Button
            size="sm"
            variant="ghost"
            className="text-accent hover:text-accent"
            disabled={ai.status === "loading"}
            onClick={explain}
            data-testid="dashboard-my-ai-btn"
          >
            {ai.status === "loading" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            {ai.status === "loading" ? t("aiExplaining") : t("myAiExplain")}
          </Button>
        )}
      </div>
      {ai.status === "error" && (
        <div className="border-b border-border bg-red-500/5 px-4 py-2 text-[12px] text-red-700 dark:text-red-400">
          {ai.message ?? t("aiSummaryFailed")}
        </div>
      )}
      {ai.status === "done" && (
        <div
          className="flex gap-2.5 border-b border-border bg-accent/5 px-4 py-3"
          data-testid="dashboard-my-ai-panel"
        >
          <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-accent">
              {t("myAiSummaryTitle")}
            </div>
            <p className="mt-1 text-[13px] leading-relaxed">{ai.text}</p>
          </div>
        </div>
      )}
      {findings.length === 0 ? (
        <div className="p-8 text-center text-sm text-muted-foreground">
          {t("myQueueEmpty")}
        </div>
      ) : (
        <ul className="divide-y divide-border">
          {findings.map((finding) => (
            <li
              key={finding.code}
              className="flex items-center gap-3 px-4 py-3"
              data-testid={`dashboard-my-action-${finding.code}`}
            >
              <span
                className={cn(
                  "flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
                  SEVERITY_STYLES[finding.severity],
                )}
              >
                <SeverityIcon severity={finding.severity} />
              </span>
              <div className="min-w-0 flex-1 text-[13px] font-medium">
                {t(`myFinding_${finding.code}`, { count: finding.count })}
              </div>
              <Button
                size="sm"
                variant="outline"
                render={<Link href={finding.href} />}
                data-testid="dashboard-my-action-cta"
              >
                {t(`myFindingCta_${finding.code}`)}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function StrengthsCard({ strengths }: { strengths: MyLoop["strengths"] }) {
  const t = useTranslations("dashboard");
  const rareIds = new Set(strengths.rare_skills.map((s) => s.competence_id));
  const rows = [
    ...strengths.top,
    ...strengths.rare_skills.filter(
      (s) => !strengths.top.some((x) => x.competence_id === s.competence_id),
    ),
  ];
  return (
    <div
      className="flex flex-col overflow-hidden rounded-xl border border-border bg-card ring-1 ring-foreground/5"
      data-testid="dashboard-my-strengths"
    >
      <div className="border-b border-border p-4">
        <h3 className="text-sm font-semibold">{t("myStrengthsTitle")}</h3>
      </div>
      {rows.length === 0 ? (
        <div className="p-8 text-center text-sm text-muted-foreground">
          {t("myStrengthsEmpty")}
        </div>
      ) : (
        <div className="flex-1 p-4">
          <ul className="space-y-2.5">
            {rows.map((s) => (
              <li key={s.competence_id} className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-[13px]">
                  {s.title}
                </span>
                {rareIds.has(s.competence_id) && (
                  <span className="rounded-full bg-accent/10 px-1.5 py-0.5 text-[11px] font-semibold text-accent">
                    {t("myRareBadge")}
                  </span>
                )}
                <span className="font-mono text-xs font-semibold tabular-nums">
                  {s.percent}%
                </span>
              </li>
            ))}
          </ul>
          {strengths.rare_skills.length > 0 && (
            <p className="mt-3 text-[11.5px] text-muted-foreground">
              {t("myRareHint")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function GrowthCard({ growth }: { growth: NonNullable<MyLoop["growth"]> }) {
  const t = useTranslations("dashboard");
  const tRef = useTranslations("reference");
  return (
    <div
      className="flex flex-col overflow-hidden rounded-xl border border-border bg-card ring-1 ring-foreground/5"
      data-testid="dashboard-my-growth"
    >
      <div className="border-b border-border p-4">
        <h3 className="text-sm font-semibold">{t("myGrowthTitle")}</h3>
      </div>
      <div className="flex-1 p-4">
        {growth.next_grade && (
          <p className="text-[13px] font-medium">
            {t("myGrowthNext", {
              grade: dictionaryItemLabel(tRef, growth.next_grade),
            })}
          </p>
        )}
        {growth.missing.length > 0 ? (
          <>
            <p className="mt-2 text-[11.5px] text-muted-foreground">
              {t("myGrowthMissing")}
            </p>
            <ul className="mt-2 space-y-1.5">
              {growth.missing.map((m) => (
                <li key={m.competence_id} className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-[13px]">
                    {m.title}
                  </span>
                  <span className="font-mono text-xs text-muted-foreground tabular-nums">
                    {m.percent !== null ? `${m.percent}%` : "—"}
                  </span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="mt-2 text-[11.5px] text-muted-foreground">
            {t("myGrowthReady")}
          </p>
        )}
      </div>
      <div className="border-t border-border bg-muted px-4 py-3 text-right">
        <Button
          size="sm"
          className="bg-accent text-accent-foreground hover:bg-accent/90"
          render={<Link href="/development" />}
          data-testid="dashboard-my-growth-cta"
        >
          {t("myGrowthCta")}
        </Button>
      </div>
    </div>
  );
}

function MyDashboard({ loop }: { loop: MyLoop }) {
  const t = useTranslations("dashboard");
  const format = useFormatter();
  const stages = buildMyStages(loop, t, (iso) =>
    format.dateTime(new Date(iso), { dateStyle: "medium" }),
  );
  return (
    <>
      <StagesHero
        title={t("myLoopTitle")}
        subtitle={t("myLoopSubtitle")}
        stages={stages}
        testidPrefix="dashboard-my-stage"
      />
      <MyActionQueue findings={loop.findings} dataVersion={loop.data_version} />
      <div className="grid gap-4 lg:grid-cols-2">
        <StrengthsCard strengths={loop.strengths} />
        {loop.growth && <GrowthCard growth={loop.growth} />}
      </div>
    </>
  );
}

// --- Active cycle ---

interface CycleStats {
  done: number;
  inProgress: number;
  notStarted: number;
  total: number;
}

function CycleCard({ stats, hasCycle }: { stats: CycleStats; hasCycle: boolean }) {
  const router = useRouter();
  const t = useTranslations("dashboard");
  const completed = stats.done;
  const pct = stats.total > 0 ? Math.round((completed / stats.total) * 100) : 0;

  const segments = [
    {
      key: "submitted",
      label: t("segmentSubmitted"),
      count: stats.done,
      className: "bg-accent",
    },
    {
      key: "inReview",
      label: t("segmentInReview"),
      count: stats.inProgress,
      className: "bg-accent/60",
    },
    {
      key: "notStarted",
      label: t("segmentNotStarted"),
      count: stats.notStarted,
      className: "bg-accent/20",
    },
  ];

  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-border bg-card ring-1 ring-foreground/5">
      <div className="flex items-center justify-between border-b border-border p-4">
        <h3 className="text-sm font-semibold">{t("cycleTitle")}</h3>
        <span className="font-mono text-[11px] text-muted-foreground">
          {hasCycle
            ? t("cycleAssessmentsCount", { count: stats.total })
            : t("noActiveCycle")}
        </span>
      </div>
      <div className="flex-1 p-4">
        {hasCycle ? (
          <>
            <div className="mb-2.5 flex items-baseline justify-between">
              <span className="text-[26px] font-bold leading-none tracking-[-0.025em]">
                {pct}%
              </span>
              <span className="text-xs text-muted-foreground">
                {t("cycleSubmittedOf", { completed, total: stats.total })}
              </span>
            </div>
            <div className="flex h-2.5 overflow-hidden rounded-full bg-muted">
              {segments.map((s) =>
                s.count > 0 ? (
                  <div
                    key={s.key}
                    className={s.className}
                    style={{ width: `${(s.count / stats.total) * 100}%` }}
                    title={`${s.label}: ${s.count}`}
                  />
                ) : null,
              )}
            </div>
            <div className="mt-3 flex flex-wrap gap-3.5 text-[11.5px]">
              {segments.map((s) => (
                <div key={s.key} className="flex items-center gap-1.5">
                  <span className={cn("h-2 w-2 rounded-sm", s.className)} />
                  <span className="text-muted-foreground">{s.label}</span>
                  <span className="font-mono font-semibold">{s.count}</span>
                </div>
              ))}
            </div>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">{t("cycleEmpty")}</p>
        )}
      </div>
      <div className="flex items-center justify-between border-t border-border bg-muted px-4 py-3">
        <span className="text-xs text-muted-foreground">
          {stats.inProgress > 0
            ? t("cycleInReviewCount", { count: stats.inProgress })
            : t("manageCycles")}
        </span>
        <Button
          size="sm"
          className="bg-accent text-accent-foreground hover:bg-accent/90"
          onClick={() => router.push("/assessments")}
          data-testid="dashboard-cycle-cta"
        >
          {t("openAssessments")}
        </Button>
      </div>
    </div>
  );
}

// --- Page ---

interface DashboardData {
  tenant: Tenant | null;
  assessments: AssessmentList | null;
  /** null → endpoint unavailable for this role, hide the loop surfaces. */
  loop: DevLoop | null;
  /** Personal loop — loaded when the company loop is unavailable. */
  myLoop: MyLoop | null;
}

const EMPTY_DATA: DashboardData = {
  tenant: null,
  assessments: null,
  loop: null,
  myLoop: null,
};

export default function DashboardPage() {
  const router = useRouter();
  const t = useTranslations("dashboard");
  const tCommon = useTranslations("common");
  const { user } = useAuth();
  const [data, setData] = useState<DashboardData>(EMPTY_DATA);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setFailed(false);
      try {
        if (!user?.is_platform_admin) {
          const onboarding = await api.get<OnboardingStatus>("/onboarding/status");
          if (onboarding.needs_onboarding) {
            router.replace("/onboarding");
            return;
          }
        }
        const [t, asmts, loop] = await Promise.allSettled([
          api.get<Tenant>("/company"),
          api.get<AssessmentList>("/assessments?limit=100"),
          api.get<DevLoop>("/analytics/dev-loop"),
        ]);
        // Company loop is admin/manager-only; a 403 (role denied) falls
        // back to the personal loop. Other failures (network, 500) keep
        // both null so a transient error doesn't flip an admin into the
        // employee view (404 on my-loop = no employee profile → neither).
        let myLoop: MyLoop | null = null;
        if (
          loop.status === "rejected" &&
          loop.reason instanceof ApiError &&
          loop.reason.status === 403
        ) {
          myLoop = await api.get<MyLoop>("/analytics/my-loop").catch(() => null);
        }
        setData({
          tenant: t.status === "fulfilled" ? t.value : null,
          assessments: asmts.status === "fulfilled" ? asmts.value : null,
          loop: loop.status === "fulfilled" ? loop.value : null,
          myLoop,
        });
        // Everything down (backend unreachable, expired session mid-race)
        // must not render as an eerily empty-but-healthy dashboard.
        setFailed(
          t.status === "rejected" &&
            asmts.status === "rejected" &&
            loop.status === "rejected" &&
            myLoop === null,
        );
      } catch {
        setFailed(true);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [router, user?.is_platform_admin, attempt]);

  const cycleStats = useMemo<CycleStats>(() => {
    const items = data.assessments?.items ?? [];
    if (items.length === 0) {
      return { done: 0, inProgress: 0, notStarted: 0, total: 0 };
    }
    let done = 0;
    let inProgress = 0;
    let notStarted = 0;
    for (const a of items) {
      if (a.status_code === "done") done++;
      else if (a.status_code === "in_progress") inProgress++;
      else notStarted++;
    }
    return { done, inProgress, notStarted, total: items.length };
  }, [data.assessments]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        {tCommon("loading")}
      </div>
    );
  }

  if (failed) {
    return (
      <div
        className="flex flex-col items-center justify-center gap-3 py-12"
        data-testid="dashboard-load-failed"
      >
        <p className="text-sm text-muted-foreground">{t("loadFailed")}</p>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setAttempt((a) => a + 1)}
        >
          {t("loadRetry")}
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold tracking-tight" data-testid="dashboard-title">
        {data.tenant?.name || t("title")}
      </h1>

      {data.loop && <DevLoopHero loop={data.loop} />}

      {data.loop && (
        <ActionQueue
          findings={data.loop.findings}
          dataVersion={data.loop.data_version}
        />
      )}

      {!data.loop && data.myLoop && <MyDashboard loop={data.myLoop} />}

      {!data.myLoop && (
        <div className="grid gap-4 lg:grid-cols-2">
          <CycleCard stats={cycleStats} hasCycle={cycleStats.total > 0} />
        </div>
      )}
    </div>
  );
}
