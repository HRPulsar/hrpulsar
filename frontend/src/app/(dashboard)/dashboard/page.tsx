"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowUpRight, Plus, Sparkles, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/context/auth-context";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  AssessmentList,
  Division,
  Employee,
  EmployeeList,
  PDP,
  Tenant,
} from "@/lib/types";

interface OnboardingStatus {
  needs_onboarding: boolean;
}

const PERIODS = ["7d", "30d", "90d", "YTD"] as const;
type Period = (typeof PERIODS)[number];

function countDivisions(divs: Division[]): number {
  return divs.reduce((acc, d) => acc + 1 + countDivisions(d.children), 0);
}

function flattenDivisions(divs: Division[]): Division[] {
  const out: Division[] = [];
  for (const d of divs) {
    out.push(d);
    if (d.children.length > 0) out.push(...flattenDivisions(d.children));
  }
  return out;
}

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

interface KpiCellProps {
  label: string;
  value: string | number;
  sub?: string;
  series?: number[];
  progress?: number;
  borderRight?: boolean;
}

function KpiCell({ label, value, sub, series, progress, borderRight = true, testId }: KpiCellProps & { testId?: string }) {
  return (
    <div
      data-testid={testId}
      className={cn("flex-1 min-w-0 p-4", borderRight && "border-r border-border")}
    >
      <div className="flex items-center justify-between">
        <span className="text-[11.5px] font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
      </div>
      <div className="mt-2.5 flex items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[26px] font-bold leading-none tracking-[-0.025em]">
            {value}
          </div>
          {sub && (
            <div className="mt-1 text-[11px] text-muted-foreground">{sub}</div>
          )}
        </div>
        {series && series.length > 1 && <Sparkline values={series} />}
      </div>
      {progress !== undefined && (
        <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-accent"
            style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
          />
        </div>
      )}
    </div>
  );
}

interface DeptRow {
  name: string;
  count: number;
}

function DeptBars({ rows, total }: { rows: DeptRow[]; total: number }) {
  if (rows.length === 0) {
    return (
      <div className="py-8 text-center text-sm text-muted-foreground">
        No employees assigned to divisions yet.
      </div>
    );
  }
  return (
    <div className="space-y-1.5">
      {rows.map((r) => {
        const pct = total > 0 ? Math.max(2, Math.round((r.count / total) * 100)) : 0;
        return (
          <div
            key={r.name}
            className="grid grid-cols-[110px_1fr_50px] items-center gap-2.5 py-1"
          >
            <div className="truncate text-[12.5px]">{r.name}</div>
            <div className="h-2 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
            </div>
            <div className="text-right font-mono text-xs text-muted-foreground tabular-nums">
              {r.count}
            </div>
          </div>
        );
      })}
    </div>
  );
}

interface CycleStats {
  done: number;
  inProgress: number;
  notStarted: number;
  total: number;
}

function CycleCard({ stats, hasCycle }: { stats: CycleStats; hasCycle: boolean }) {
  const router = useRouter();
  const completed = stats.done;
  const pct = stats.total > 0 ? Math.round((completed / stats.total) * 100) : 0;

  const segments = [
    { key: "Submitted", count: stats.done, className: "bg-accent" },
    { key: "In review", count: stats.inProgress, className: "bg-accent/60" },
    { key: "Not started", count: stats.notStarted, className: "bg-accent/20" },
  ];

  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-border bg-card ring-1 ring-foreground/5">
      <div className="flex items-center justify-between border-b border-border p-4">
        <h3 className="text-sm font-semibold">Active assessment cycle</h3>
        <span className="font-mono text-[11px] text-muted-foreground">
          {hasCycle ? `${stats.total} assessments` : "no active cycle"}
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
                {completed} of {stats.total} submitted
              </span>
            </div>
            <div className="flex h-2.5 overflow-hidden rounded-full bg-muted">
              {segments.map((s) =>
                s.count > 0 ? (
                  <div
                    key={s.key}
                    className={s.className}
                    style={{ width: `${(s.count / stats.total) * 100}%` }}
                    title={`${s.key}: ${s.count}`}
                  />
                ) : null,
              )}
            </div>
            <div className="mt-3 flex flex-wrap gap-3.5 text-[11.5px]">
              {segments.map((s) => (
                <div key={s.key} className="flex items-center gap-1.5">
                  <span className={cn("h-2 w-2 rounded-sm", s.className)} />
                  <span className="text-muted-foreground">{s.key}</span>
                  <span className="font-mono font-semibold">{s.count}</span>
                </div>
              ))}
            </div>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            No assessment cycle is in progress.
          </p>
        )}
      </div>
      <div className="flex items-center justify-between border-t border-border bg-muted px-4 py-3">
        <span className="text-xs text-muted-foreground">
          {stats.inProgress > 0
            ? `${stats.inProgress} in review`
            : "Manage cycles in Assessments"}
        </span>
        <Button
          size="sm"
          className="bg-accent text-accent-foreground hover:bg-accent/90"
          onClick={() => router.push("/assessments")}
          data-testid="dashboard-cycle-cta"
        >
          Open assessments
        </Button>
      </div>
    </div>
  );
}

interface InboxItem {
  tone: "alert" | "info";
  title: string;
  sub: string;
  action: string;
  href: string;
}

function buildInbox(assessments: AssessmentList | null, pdps: PDP[]): InboxItem[] {
  const out: InboxItem[] = [];
  const inProgress =
    assessments?.items.filter((a) => a.status_code === "in_progress").length ?? 0;
  if (inProgress > 0) {
    out.push({
      tone: "alert",
      title: `${inProgress} assessment${inProgress > 1 ? "s" : ""} in progress`,
      sub: "Cycle awaiting completion",
      action: "Review",
      href: "/assessments",
    });
  }
  const draftPdps = pdps.filter((p) => p.status === "draft").length;
  if (draftPdps > 0) {
    out.push({
      tone: "info",
      title: `${draftPdps} development plan${draftPdps > 1 ? "s" : ""} in draft`,
      sub: "Pending review",
      action: "Open",
      href: "/development",
    });
  }
  const overdue = pdps.filter(
    (p) =>
      p.status !== "completed" && p.deadline && new Date(p.deadline) < new Date(),
  ).length;
  if (overdue > 0) {
    out.push({
      tone: "alert",
      title: `${overdue} development plan${overdue > 1 ? "s" : ""} overdue`,
      sub: "Past deadline",
      action: "Open",
      href: "/development",
    });
  }
  return out.slice(0, 4);
}

function InboxCard({ items }: { items: InboxItem[] }) {
  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-border bg-card ring-1 ring-foreground/5">
      <div className="flex items-center justify-between border-b border-border p-4">
        <h3 className="text-sm font-semibold">Needs your attention</h3>
        <span className="rounded-full bg-accent/10 px-1.5 py-0.5 text-[11px] font-semibold text-accent">
          {items.length} item{items.length === 1 ? "" : "s"}
        </span>
      </div>
      {items.length === 0 ? (
        <div className="p-8 text-center text-sm text-muted-foreground">
          You&apos;re all caught up.
        </div>
      ) : (
        <ul className="divide-y divide-border">
          {items.map((item, i) => (
            <li
              key={i}
              className="flex items-center gap-3 px-4 py-3"
              data-testid="dashboard-inbox-row"
            >
              <span
                className={cn(
                  "flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
                  item.tone === "alert"
                    ? "bg-red-500/10 text-red-700 dark:text-red-400"
                    : "bg-accent/10 text-accent",
                )}
              >
                {item.tone === "alert" ? (
                  <AlertTriangle className="h-3.5 w-3.5" />
                ) : (
                  <Sparkles className="h-3.5 w-3.5" />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium">{item.title}</div>
                <div className="mt-0.5 text-[11.5px] text-muted-foreground">
                  {item.sub}
                </div>
              </div>
              <Button
                size="sm"
                variant="outline"
                render={<Link href={item.href} />}
              >
                {item.action}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CalendarCard() {
  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-border bg-card ring-1 ring-foreground/5">
      <div className="border-b border-border p-4">
        <h3 className="text-sm font-semibold">This week</h3>
      </div>
      <div className="flex-1 p-8 text-center text-sm text-muted-foreground">
        No scheduled events.
      </div>
    </div>
  );
}

interface DashboardData {
  tenant: Tenant | null;
  employeeCount: number;
  activeEmployeeCount: number;
  divisionCount: number;
  divisions: Division[];
  employees: Employee[];
  assessments: AssessmentList | null;
  pdps: PDP[];
}

const EMPTY_DATA: DashboardData = {
  tenant: null,
  employeeCount: 0,
  activeEmployeeCount: 0,
  divisionCount: 0,
  divisions: [],
  employees: [],
  assessments: null,
  pdps: [],
};

export default function DashboardPage() {
  const router = useRouter();
  const { user } = useAuth();
  const [data, setData] = useState<DashboardData>(EMPTY_DATA);
  const [period, setPeriod] = useState<Period>("30d");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        if (!user?.is_platform_admin) {
          const onboarding = await api.get<OnboardingStatus>("/onboarding/status");
          if (onboarding.needs_onboarding) {
            router.replace("/onboarding");
            return;
          }
        }
        const [t, eList, divs, asmts, pdps, allEmps] = await Promise.allSettled([
          api.get<Tenant>("/company"),
          api.get<EmployeeList>("/employees?limit=1"),
          api.get<Division[]>("/divisions"),
          api.get<AssessmentList>("/assessments?limit=100"),
          api.get<PDP[]>("/pdp"),
          api.get<EmployeeList>("/employees?limit=100"),
        ]);
        const employees =
          allEmps.status === "fulfilled" ? allEmps.value.items : [];
        const activeEmployeeCount = employees.filter(
          (e) => e.status === "active",
        ).length;
        setData({
          tenant: t.status === "fulfilled" ? t.value : null,
          employeeCount:
            eList.status === "fulfilled"
              ? eList.value.total
              : employees.length,
          activeEmployeeCount,
          divisions: divs.status === "fulfilled" ? divs.value : [],
          divisionCount:
            divs.status === "fulfilled" ? countDivisions(divs.value) : 0,
          employees,
          assessments: asmts.status === "fulfilled" ? asmts.value : null,
          pdps: pdps.status === "fulfilled" ? pdps.value : [],
        });
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [router, user?.is_platform_admin]);

  const deptRows = useMemo<DeptRow[]>(() => {
    const flat = flattenDivisions(data.divisions);
    const nameById = new Map(flat.map((d) => [d.id, d.name]));
    const counts = new Map<string, number>();
    for (const emp of data.employees) {
      const key = emp.division_id ? nameById.get(emp.division_id) : null;
      const label = key ?? "Unassigned";
      counts.set(label, (counts.get(label) ?? 0) + 1);
    }
    return [...counts.entries()]
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 7);
  }, [data.divisions, data.employees]);

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

  const inbox = useMemo(
    () => buildInbox(data.assessments, data.pdps),
    [data.assessments, data.pdps],
  );

  const activeReviews = cycleStats.inProgress + cycleStats.notStarted;
  const openPdpCount = data.pdps.filter((p) => p.status !== "completed").length;
  const activePct =
    data.employeeCount > 0
      ? Math.round((data.activeEmployeeCount / data.employeeCount) * 100)
      : 0;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        Loading...
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight" data-testid="dashboard-title">
            {data.tenant?.name || "Dashboard"}
          </h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Organization health · {data.employeeCount} {data.employeeCount === 1 ? "person" : "people"} · {data.divisionCount} division{data.divisionCount === 1 ? "" : "s"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div
            role="tablist"
            aria-label="Period"
            className="flex items-center gap-0.5 rounded-md bg-muted p-0.5"
          >
            {PERIODS.map((p) => {
              const active = period === p;
              return (
                <button
                  key={p}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => setPeriod(p)}
                  className={cn(
                    "rounded px-2.5 py-1 text-[11.5px] transition-colors",
                    active
                      ? "bg-card font-semibold text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                  data-testid={`dashboard-period-${p}`}
                >
                  {p}
                </button>
              );
            })}
          </div>
          <Button
            render={<Link href="/employees" />}
            data-testid="dashboard-btn-add-employee"
          >
            <Plus className="h-4 w-4" />
            Add employee
          </Button>
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-card ring-1 ring-foreground/5">
        <div className="flex flex-wrap">
          <KpiCell
            testId="dashboard-kpi-headcount"
            label="Headcount"
            value={data.employeeCount}
            sub={
              data.activeEmployeeCount === data.employeeCount
                ? "all active"
                : `${data.activeEmployeeCount} active`
            }
            series={[
              data.employeeCount,
              data.employeeCount,
              data.employeeCount,
              data.employeeCount,
              data.employeeCount,
              data.employeeCount,
              data.employeeCount,
              data.employeeCount,
            ]}
          />
          <KpiCell
            testId="dashboard-kpi-active-reviews"
            label="Active reviews"
            value={activeReviews}
            sub={
              cycleStats.inProgress > 0
                ? `${cycleStats.inProgress} in progress`
                : "no active cycle"
            }
            series={[activeReviews, activeReviews, activeReviews, activeReviews]}
          />
          <KpiCell
            testId="dashboard-kpi-divisions"
            label="Divisions"
            value={data.divisionCount}
            sub={`${deptRows.length} with people`}
            series={[
              data.divisionCount,
              data.divisionCount,
              data.divisionCount,
              data.divisionCount,
            ]}
          />
          <KpiCell
            testId="dashboard-kpi-open-pdps"
            label="Open dev plans"
            value={openPdpCount}
            sub={`${activePct}% of org active`}
            progress={activePct}
            borderRight={false}
          />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <div className="overflow-hidden rounded-xl border border-border bg-card ring-1 ring-foreground/5">
          <div className="flex items-center justify-between border-b border-border p-4">
            <div>
              <h3 className="text-sm font-semibold">Headcount by department</h3>
              <p className="mt-0.5 text-[11.5px] text-muted-foreground">
                Last {period} · % of org
              </p>
            </div>
            <Link
              href="/analytics"
              className="inline-flex items-center gap-1 text-xs font-medium text-accent transition-colors hover:underline"
            >
              Open analytics
              <ArrowUpRight className="h-3 w-3" />
            </Link>
          </div>
          <div className="px-4 pt-2 pb-4">
            <DeptBars rows={deptRows} total={data.employeeCount} />
          </div>
        </div>

        <CycleCard
          stats={cycleStats}
          hasCycle={cycleStats.total > 0}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <InboxCard items={inbox} />
        <CalendarCard />
      </div>
    </div>
  );
}