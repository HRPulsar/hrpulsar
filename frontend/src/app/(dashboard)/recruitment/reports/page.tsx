"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import {
  reportSectionLabel,
  type ReportExport,
  type ReportExportList,
  type ReportSectionCode,
  type ReportStatus,
  type Vacancy,
  type VacancyList,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Download, FileSpreadsheet, Loader2, RefreshCw, Share2, Trash2 } from "lucide-react";
import { formatDateTime } from "@/lib/date-format";
import { toast } from "sonner";
import { RecruitmentBreadcrumbs, RecruitmentTabs } from "@/components/recruitment";
import { RecruitmentShareDialog } from "@/components/recruitment/share-dialog";
import { BADGE_COLOR } from "@/lib/badge-tones";

const STATUS_COLORS: Record<ReportStatus, string> = {
  pending: BADGE_COLOR.blue,
  processing: BADGE_COLOR.yellow,
  completed: BADGE_COLOR.green,
  failed: BADGE_COLOR.red,
};

export default function ReportsListPage() {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [items, setItems] = useState<ReportExport[]>([]);
  const [vacancies, setVacancies] = useState<Vacancy[]>([]);
  const [loading, setLoading] = useState(true);
  const [vacancyFilter, setVacancyFilter] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [shareReportId, setShareReportId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (vacancyFilter) params.set("vacancy_id", vacancyFilter);
      if (statusFilter) params.set("status", statusFilter);
      const qs = params.toString();
      const res = await api.get<ReportExportList>(
        qs ? `/recruitment/reports?${qs}` : "/recruitment/reports",
      );
      setItems(res.items);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("reportsLoadFailed"),
      );
    } finally {
      setLoading(false);
    }
  }, [vacancyFilter, statusFilter, t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    api
      .get<VacancyList>("/recruitment/vacancies?limit=100")
      .then((res) => setVacancies(res.items))
      .catch(() => setVacancies([]));
  }, []);

  const vacancyTitleById = useMemo(() => {
    const m: Record<string, string> = {};
    vacancies.forEach((v) => {
      m[v.id] = v.title;
    });
    return m;
  }, [vacancies]);

  async function handleDownload(exportRow: ReportExport) {
    try {
      const fresh = await api.get<ReportExport>(
        `/recruitment/reports/${exportRow.id}`,
      );
      if (fresh.download_url) {
        window.open(fresh.download_url, "_blank", "noopener");
      } else {
        toast.error(t("reportsFileNotReady"));
      }
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("reportsLinkFailed"),
      );
    }
  }

  async function handleDelete(exportId: string) {
    try {
      await api.delete(`/recruitment/reports/${exportId}`);
      toast.success(t("reportsToastDeleted"));
      void refresh();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("reportsDeleteFailed"),
      );
    }
  }

  return (
    <div className="space-y-6" data-testid="recruitment-reports-page">
      <RecruitmentBreadcrumbs
        segments={[
          { label: t("breadcrumbReports") },
        ]}
      />
      <RecruitmentTabs />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {t("reportsTitle")}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("reportsDescription")}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void refresh()}
          data-testid="recruitment-reports-page-btn-refresh"
        >
          <RefreshCw className="size-4" /> {t("actionRefresh")}
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select
          className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm"
          value={vacancyFilter}
          onChange={(e) => setVacancyFilter(e.target.value)}
          data-testid="recruitment-reports-filter-vacancy"
        >
          <option value="">{t("reportsFilterAllVacancies")}</option>
          {vacancies.map((v) => (
            <option key={v.id} value={v.id}>
              {v.title}
            </option>
          ))}
        </select>
        <select
          className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          data-testid="recruitment-reports-filter-status"
        >
          <option value="">{t("filterAllStatuses")}</option>
          <option value="pending">{t("reportsFilterStatusPending")}</option>
          <option value="processing">{t("reportsFilterStatusProcessing")}</option>
          <option value="completed">{t("reportsFilterStatusCompleted")}</option>
          <option value="failed">{t("reportsFilterStatusFailed")}</option>
        </select>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12 text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          <span className="ml-2">{t("loading")}</span>
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-dashed p-12 text-center">
          <FileSpreadsheet className="mx-auto mb-3 h-10 w-10 text-muted-foreground opacity-40" />
          <p className="text-sm font-medium text-muted-foreground">
            {t("reportsEmpty")}
          </p>
        </div>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{tc("vacancy")}</TableHead>
                <TableHead>{t("reportsColRequested")}</TableHead>
                <TableHead>{t("reportsColSections")}</TableHead>
                <TableHead>{t("columnStatus")}</TableHead>
                <TableHead className="w-[140px] text-right">
                  {t("columnActions")}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((row) => (
                <TableRow key={row.id}>
                  <TableCell className="font-medium">
                    <div className="flex flex-col gap-0.5">
                      <Link
                        className="hover:underline"
                        href={`/recruitment/requisitions/${row.vacancy_id}`}
                      >
                        {vacancyTitleById[row.vacancy_id] || row.vacancy_id}
                      </Link>
                      <Link
                        className="text-xs text-muted-foreground hover:underline"
                        href={`/recruitment/reports/${row.id}`}
                        data-testid={`recruitment-reports-open-${row.id}`}
                      >
                        {t("reportsOpenPreview")}
                      </Link>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="text-sm">
                      {formatDateTime(row.created_at)}
                    </div>
                    {row.requested_by_name && (
                      <div className="text-xs text-muted-foreground">
                        {row.requested_by_name}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {row.sections.map((s: ReportSectionCode) => (
                        <Badge key={s} variant="secondary" className="text-xs">
                          {reportSectionLabel(t, s)}
                        </Badge>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant="secondary"
                      className={STATUS_COLORS[row.status] || ""}
                    >
                      {row.status}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={row.status !== "completed"}
                        onClick={() => void handleDownload(row)}
                      >
                        <Download className="size-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={row.status !== "completed"}
                        onClick={() => setShareReportId(row.id)}
                        data-testid={`recruitment-reports-share-${row.id}`}
                      >
                        <Share2 className="size-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => void handleDelete(row.id)}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {shareReportId && (
        <RecruitmentShareDialog
          reportId={shareReportId}
          open={!!shareReportId}
          onClose={() => setShareReportId(null)}
        />
      )}
    </div>
  );
}
