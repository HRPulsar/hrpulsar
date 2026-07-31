"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { Vacancy, VacancyList } from "@/lib/types";
import { formatDate } from "@/lib/date-format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Pagination } from "@/components/pagination";
import { usePermissions } from "@/hooks/use-permissions";
import { RecruitmentBreadcrumbs, RecruitmentTabs } from "@/components/recruitment";
import { Briefcase, Plus, Search, X } from "lucide-react";
import { VacancyActionsMenu } from "./_components/VacancyActionsMenu";
import {
  VACANCY_STATUS_COLORS,
  VACANCY_STATUS_OPTIONS,
  vacancyStatusBadgeLabel,
  vacancyStatusOptionLabel,
} from "@/lib/vacancy-status";

const PAGE_SIZE = 25;

export default function VacancyListPage() {
  const router = useRouter();
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [vacancies, setVacancies] = useState<Vacancy[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [filterStatus, setFilterStatus] = useState("");

  const { canManage } = usePermissions();

  const isArchivedView = filterStatus === "__archived__";

  const loadVacancies = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(PAGE_SIZE));
      if (filterStatus === "__archived__") {
        params.set("archived", "only");
      } else if (filterStatus) {
        params.set("status", filterStatus);
      } else {
        // HRP-363: "All statuses" must include archived vacancies too.
        params.set("archived", "include");
      }
      const data = await api.get<VacancyList>(`/recruitment/vacancies?${params}`);
      setVacancies(data.items);
      setTotal(data.total);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [page, filterStatus]);

  useEffect(() => {
    loadVacancies();
  }, [loadVacancies]);

  function applyFilter(status: string) {
    setFilterStatus(status);
    setPage(1);
  }

  function clearFilters() {
    setSearchQuery("");
    setFilterStatus("");
    setPage(1);
  }

  const hasFilters = searchQuery || filterStatus;

  const filtered = searchQuery
    ? vacancies.filter(
        (v) =>
          v.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
          (v.position_title || "").toLowerCase().includes(searchQuery.toLowerCase()),
      )
    : vacancies;

  // HRP-290 follow-up: the status/archived filter is applied server-side, so
  // the server `total` already respects it and covers all pages — the header
  // must show it, not the loaded page's length. Only the search box filters
  // the loaded page client-side; count `filtered` just in that case.
  const displayCount = searchQuery ? filtered.length : total;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        {tc("loading")}
      </div>
    );
  }

  return (
    <div data-testid="recruitment-vacancy-list" className="space-y-6">
      <RecruitmentBreadcrumbs segments={[{ label: t("vacanciesTitle") }]} />
      <RecruitmentTabs />
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {t("vacanciesTitle")}
          </h1>
          {/* HRP-290: counter respects active filters (Assessments parity). */}
          <p
            className="text-sm text-muted-foreground"
            data-testid="recruitment-vacancy-count"
          >
            {t("vacancyCount", { count: displayCount })}
          </p>
        </div>
        {canManage && (
          <Button
            data-testid="recruitment-btn-create-vacancy"
            size="sm"
            onClick={() => router.push("/recruitment/requisitions/new")}
          >
            <Plus className="mr-1 h-4 w-4" />
            {t("vacancyCreateButton")}
          </Button>
        )}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-48">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            data-testid="recruitment-vacancy-input-search"
            placeholder={t("vacancySearchPlaceholder")}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-8"
          />
        </div>
        <Select value={filterStatus} onValueChange={(val) => applyFilter(val)}>
          <SelectTrigger
            className="w-36"
            data-testid="vacancy-status-filter"
          >
            <SelectValue placeholder={t("filterAllStatuses")}>
              {filterStatus === "__archived__"
                ? t("statusArchived")
                : filterStatus
                  ? vacancyStatusOptionLabel(t, filterStatus)
                  : t("filterAllStatuses")}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="">{t("filterAllStatuses")}</SelectItem>
            {VACANCY_STATUS_OPTIONS.map((s) => (
              <SelectItem key={s} value={s}>
                {vacancyStatusOptionLabel(t, s)}
              </SelectItem>
            ))}
            <SelectItem value="__archived__">{t("statusArchived")}</SelectItem>
          </SelectContent>
        </Select>
        {hasFilters && (
          <Button variant="ghost" size="sm" onClick={clearFilters}>
            <X className="mr-1 h-3 w-3" />
            {t("actionClear")}
          </Button>
        )}
      </div>

      {filtered.length === 0 ? (
        <div
          data-testid="recruitment-vacancy-empty"
          className="rounded-lg border border-dashed p-12 text-center text-muted-foreground"
        >
          <Briefcase className="mx-auto mb-3 h-10 w-10 opacity-40" />
          <p className="text-sm font-medium">
            {isArchivedView
              ? t("vacanciesEmptyArchived")
              : hasFilters
                ? t("vacanciesEmptyFiltered")
                : t("vacanciesEmpty")}
          </p>
          {!hasFilters && canManage && (
            <p className="mt-1 text-xs">{t("vacanciesEmptyHint")}</p>
          )}
        </div>
      ) : (
        <>
          <div className="rounded-lg border">
            <Table data-testid="recruitment-vacancy-table">
              <TableHeader>
                <TableRow>
                  <TableHead>{t("columnTitle")}</TableHead>
                  <TableHead>{t("columnPosition")}</TableHead>
                  <TableHead>{t("columnDivision")}</TableHead>
                  <TableHead>{t("columnStatus")}</TableHead>
                  <TableHead>{t("candidatesTitle")}</TableHead>
                  <TableHead>{t("columnOwner")}</TableHead>
                  <TableHead>{t("columnCreated")}</TableHead>
                  <TableHead className="w-12 text-right"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((vacancy) => {
                  const isArchived = !!vacancy.archived_at;
                  return (
                    <TableRow
                      key={vacancy.id}
                      data-testid={`vacancy-list-row-${vacancy.id}`}
                      className={isArchived ? "opacity-60" : ""}
                    >
                      <TableCell className="font-medium">
                        <Link
                          href={`/recruitment/requisitions/${vacancy.id}`}
                          className="hover:underline"
                          data-testid={`recruitment-vacancy-row-${vacancy.id}-title`}
                        >
                          {vacancy.title}
                        </Link>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {vacancy.position_title || "---"}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {vacancy.division_name || "---"}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="secondary"
                          className={
                            isArchived
                              ? "bg-muted text-muted-foreground"
                              : VACANCY_STATUS_COLORS[vacancy.status] || ""
                          }
                        >
                          {isArchived
                            ? t("vacancyBadgeArchived")
                            : vacancyStatusBadgeLabel(t, vacancy.status)}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {vacancy.candidates_count ?? 0}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {vacancy.owner_name || "---"}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDate(vacancy.created_at)}
                      </TableCell>
                      <TableCell className="text-right">
                        {canManage && (
                          <VacancyActionsMenu
                            vacancy={vacancy}
                            onChanged={loadVacancies}
                          />
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
          <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        </>
      )}
    </div>
  );
}
