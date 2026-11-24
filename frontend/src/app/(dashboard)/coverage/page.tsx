"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { CircleHelp, Plus, Search, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Hint } from "@/components/ui/hint";
import { Input } from "@/components/ui/input";
import { MultiSelectFilter } from "@/components/multi-select-filter";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { LoadErrorState } from "@/components/load-error-state";
import { ContainerActions } from "@/components/coverage/container-actions";
import { EmployeeSummaryLine } from "@/components/employee/employee-summary-line";
import { usePermissions } from "@/hooks/use-permissions";
import { BADGE_COLOR } from "@/lib/badge-tones";
import { formatDate } from "@/lib/date-format";
import {
  type ContainerStatus,
  type ContainerType,
  type WorkContainer,
  workApi,
} from "@/lib/api/work";

const STATUS_COLOR: Record<ContainerStatus, string> = {
  draft: BADGE_COLOR.neutral,
  active: BADGE_COLOR.green,
  archived: BADGE_COLOR.neutral,
};

const TYPES: ContainerType[] = ["process", "initiative"];
const STATUSES: ContainerStatus[] = ["draft", "active", "archived"];

/** HRP-862: the share of the estimated hours an agent of the company already
 * does, as the coverage last computed it - the list computes nothing. Null
 * until the coverage was opened once, or while no step carries an estimate. */
function automatedShare(c: WorkContainer): number | null {
  return c.coverage_summary?.automated_share ?? null;
}

function automatedPercent(c: WorkContainer): string {
  const share = automatedShare(c);
  return share === null ? "—" : `${Math.round(share)}%`;
}

export default function CoveragePage() {
  const t = useTranslations("coverage");
  const tc = useTranslations("common");
  const tSections = useTranslations("sections");
  const { canCreateCoverage } = usePermissions();
  const [items, setItems] = useState<WorkContainer[] | null>(null);
  const [failed, setFailed] = useState(false);
  // HRP-859 REDO: the filters of every other list (/assessments). The list is
  // loaded whole, so they filter here; the counts follow them (HRP-1056).
  // ponytail: whole = the first 200 the API gives; server-side filters if a
  // company ever keeps more.
  const [search, setSearch] = useState("");
  const [types, setTypes] = useState<string[]>([]);
  const [statuses, setStatuses] = useState<string[]>([]);
  const [reloadKey, setReloadKey] = useState(0);
  const [howOpen, setHowOpen] = useState(false);
  const retry = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let stale = false;
    workApi
      .listContainers()
      .then((res) => {
        if (stale) return;
        setItems(res.items);
        setFailed(false);
      })
      .catch(() => {
        if (!stale) setFailed(true);
      });
    return () => {
      stale = true;
    };
  }, [reloadKey]);

  const query = search.trim().toLocaleLowerCase();
  const shown = items?.filter(
    (c) =>
      (!query || c.title.toLocaleLowerCase().includes(query)) &&
      (types.length === 0 || types.includes(c.type)) &&
      (statuses.length === 0 || statuses.includes(c.status)),
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold" data-testid="coverage-heading">
              {t("title")}
            </h1>
            {/* Also says what a process and a project are (HRP-859 REDO). */}
            <Hint text={tSections("coverage.hint")} data-testid="coverage-hint-title" />
          </div>
          {shown && items && items.length > 0 && (
            <p className="text-sm text-muted-foreground" data-testid="coverage-count">
              {t("listCount", {
                processes: shown.filter((c) => c.type === "process").length,
                projects: shown.filter((c) => c.type === "initiative").length,
              })}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* HRP-1207: what the section does, said once here rather than
              on every breakdown (HRP-1231). */}
          <Button variant="outline" onClick={() => setHowOpen(true)} data-testid="coverage-btn-how">
            <CircleHelp className="size-4" />
            {t("howItWorks")}
          </Button>
          {canCreateCoverage && (
            <Link href="/coverage/new" className={buttonVariants()} data-testid="coverage-btn-create">
              <Plus className="size-4" />
              {t("create")}
            </Link>
          )}
        </div>
      </div>

      <Dialog open={howOpen} onOpenChange={setHowOpen}>
        <DialogContent className="sm:max-w-lg" data-testid="coverage-how-dialog">
          <DialogHeader>
            <DialogTitle>{t("howItWorks")}</DialogTitle>
            <DialogDescription>{t("howItWorksText")}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button onClick={() => setHowOpen(false)} data-testid="coverage-how-btn-ok">
              {t("howItWorksOk")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {items && items.length > 0 && (
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative min-w-48 flex-1">
            <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              data-testid="coverage-input-search"
              placeholder={t("searchPlaceholder")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8"
            />
          </div>
          <MultiSelectFilter
            data-testid="coverage-multi-types"
            options={TYPES.map((value) => ({ value, label: t(`type_${value}`) }))}
            value={types}
            onChange={setTypes}
            placeholder={t("allTypes")}
            className="w-36"
          />
          <MultiSelectFilter
            data-testid="coverage-multi-statuses"
            options={STATUSES.map((value) => ({ value, label: t(`status_${value}`) }))}
            value={statuses}
            onChange={setStatuses}
            placeholder={t("allStatuses")}
            className="w-36"
          />
          {/* HRP-859 REDO: like /assessments - shown once any filter is set,
              resets them all. */}
          {(search || types.length > 0 || statuses.length > 0) && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setSearch("");
                setTypes([]);
                setStatuses([]);
              }}
              data-testid="coverage-btn-clear-filters"
            >
              <X className="mr-1 h-3 w-3" />
              {tc("clear")}
            </Button>
          )}
        </div>
      )}

      {failed ? (
        <LoadErrorState onRetry={retry} testIdPrefix="coverage" />
      ) : items === null || shown === undefined ? (
        <div className="py-12 text-center text-muted-foreground">{tc("loading")}</div>
      ) : items.length === 0 ? (
        <div
          className="rounded-lg border border-dashed p-10 text-center"
          data-testid="coverage-empty"
        >
          <p className="text-lg font-medium">{t("emptyTitle")}</p>
          <p className="mt-1 text-sm text-muted-foreground">{t("emptyText")}</p>
          {canCreateCoverage && (
            <div className="mt-5 flex flex-wrap justify-center gap-2">
              <Link
                href="/coverage/new?type=process"
                className={buttonVariants()}
                data-testid="coverage-btn-create-process"
              >
                {t("describeProcess")}
              </Link>
              <Link
                href="/coverage/new?type=initiative"
                className={buttonVariants({ variant: "outline" })}
                data-testid="coverage-btn-create-initiative"
              >
                {t("planInitiative")}
              </Link>
            </div>
          )}
        </div>
      ) : shown.length === 0 ? (
        <div
          className="rounded-lg border border-dashed p-12 text-center text-muted-foreground"
          data-testid="coverage-empty-filtered"
        >
          {t("emptyFiltered")}
        </div>
      ) : (
        <Table data-testid="coverage-table">
          <TableHeader>
            <TableRow>
              <TableHead>{t("colTitle")}</TableHead>
              <TableHead>{t("colType")}</TableHead>
              <TableHead>{t("colStatus")}</TableHead>
              <TableHead>{t("colOwner")}</TableHead>
              <TableHead>
                {/* HRP-1194: what the percent counts, behind a "?" as by
                    the section's title. */}
                <span className="inline-flex items-center gap-1">
                  {t("colAutomated")}
                  <Hint text={t("colAutomatedHint")} data-testid="coverage-col-automated-hint" />
                </span>
              </TableHead>
              <TableHead>{t("colUpdated")}</TableHead>
              {/* HRP-1228: the row's kebab; its column is named for screen
                  readers only. */}
              <TableHead className="w-10">
                <span className="sr-only">{t("actionsAria")}</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((c) => (
              <TableRow key={c.id} data-testid={`coverage-row-${c.id}`}>
                <TableCell>
                  <Link href={`/coverage/${c.id}`} className="font-medium hover:underline">
                    {c.title}
                  </Link>
                </TableCell>
                <TableCell>{t(`type_${c.type}`)}</TableCell>
                <TableCell>
                  <Badge className={STATUS_COLOR[c.status]}>{t(`status_${c.status}`)}</Badge>
                </TableCell>
                {/* HRP-810 REDO: the owner like any employee - name, position,
                    status chip when they are not active. */}
                <TableCell data-testid={`coverage-row-${c.id}-owner`}>
                  {c.owner ? (
                    <EmployeeSummaryLine
                      employeeId={c.owner.employee_id}
                      employee={{
                        user_name: c.owner.name,
                        position_title: c.owner.position_title,
                        status: c.owner.status,
                      }}
                    />
                  ) : (
                    <span className="text-muted-foreground">{t("accessOwnerNone")}</span>
                  )}
                </TableCell>
                <TableCell
                  className="tabular-nums"
                  data-testid={`coverage-row-${c.id}-automated`}
                  data-share={automatedShare(c) ?? ""}
                >
                  {automatedPercent(c)}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDate(c.updated_at)}
                </TableCell>
                <TableCell className="text-right">
                  <ContainerActions
                    container={c}
                    testIdPrefix={`coverage-row-${c.id}-btn`}
                    // Whatever it did, the list is read again.
                    onChanged={retry}
                    onDeleted={retry}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
