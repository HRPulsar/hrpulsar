"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Plus, Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
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
  // loaded whole, so they filter here and the counts stay the full ones.
  // ponytail: whole = the first 200 the API gives; server-side filters if a
  // company ever keeps more.
  const [search, setSearch] = useState("");
  const [types, setTypes] = useState<string[]>([]);
  const [statuses, setStatuses] = useState<string[]>([]);
  const [reloadKey, setReloadKey] = useState(0);
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
          {items && items.length > 0 && (
            <p className="text-sm text-muted-foreground" data-testid="coverage-count">
              {t("listCount", {
                processes: items.filter((c) => c.type === "process").length,
                projects: items.filter((c) => c.type === "initiative").length,
              })}
            </p>
          )}
        </div>
        {canCreateCoverage && (
          <Link href="/coverage/new" className={buttonVariants()} data-testid="coverage-btn-create">
            <Plus className="size-4" />
            {t("create")}
          </Link>
        )}
      </div>

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
              <TableHead>{t("colAutomated")}</TableHead>
              <TableHead>{t("colUpdated")}</TableHead>
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
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
