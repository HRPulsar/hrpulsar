"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Hint } from "@/components/ui/hint";
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

const TYPE_FILTERS: Array<{ value: ContainerType | "all"; key: string }> = [
  { value: "all", key: "filterAll" },
  { value: "process", key: "filterProcesses" },
  { value: "initiative", key: "filterProjects" },
];

export default function CoveragePage() {
  const t = useTranslations("coverage");
  const tc = useTranslations("common");
  const tSections = useTranslations("sections");
  const { canCreateCoverage } = usePermissions();
  const [items, setItems] = useState<WorkContainer[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [type, setType] = useState<ContainerType | "all">("all");
  const [reloadKey, setReloadKey] = useState(0);
  const retry = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let stale = false;
    workApi
      .listContainers(type === "all" ? undefined : type)
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
  }, [type, reloadKey]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold" data-testid="coverage-heading">
            {t("title")}
          </h1>
          <Hint text={tSections("coverage.hint")} data-testid="coverage-hint-title" />
        </div>
        {canCreateCoverage && (
          <Link href="/coverage/new" className={buttonVariants()} data-testid="coverage-btn-create">
            <Plus className="size-4" />
            {t("create")}
          </Link>
        )}
      </div>

      <div className="flex gap-1" role="group" aria-label={t("filterLabel")}>
        {TYPE_FILTERS.map((f) => (
          <Button
            key={f.value}
            size="sm"
            variant={type === f.value ? "default" : "outline"}
            onClick={() => setType(f.value)}
            data-testid={`coverage-filter-${f.value}`}
          >
            {t(f.key)}
          </Button>
        ))}
      </div>

      {failed ? (
        <LoadErrorState onRetry={retry} testIdPrefix="coverage" />
      ) : items === null ? (
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
      ) : (
        <Table data-testid="coverage-table">
          <TableHeader>
            <TableRow>
              <TableHead>{t("colTitle")}</TableHead>
              <TableHead>{t("colType")}</TableHead>
              <TableHead>{t("colStatus")}</TableHead>
              <TableHead>{t("colUpdated")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((c) => (
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
