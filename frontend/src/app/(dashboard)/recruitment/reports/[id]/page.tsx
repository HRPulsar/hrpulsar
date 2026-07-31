"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { use } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import {
  reportSectionLabel,
  type ReportExport,
  type ReportPreview,
  type ReportSectionCode,
  type ReportStatus,
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Download, FileSpreadsheet, Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { RecruitmentBreadcrumbs } from "@/components/recruitment";
import { BADGE_COLOR } from "@/lib/badge-tones";

const STATUS_COLORS: Record<ReportStatus, string> = {
  pending: BADGE_COLOR.blue,
  processing: BADGE_COLOR.yellow,
  completed: BADGE_COLOR.green,
  failed: BADGE_COLOR.red,
};

function formatCell(value: string | number | boolean | null): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "✓" : "";
  return String(value);
}

export default function ReportDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const t = useTranslations("recruitment");
  const [report, setReport] = useState<ReportExport | null>(null);
  const [preview, setPreview] = useState<ReportPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [activeSheet, setActiveSheet] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const reportRes = await api.get<ReportExport>(
        `/recruitment/reports/${id}`,
      );
      setReport(reportRes);
      if (reportRes.status === "completed") {
        try {
          const previewRes = await api.get<ReportPreview>(
            `/recruitment/reports/${id}/preview`,
          );
          setPreview(previewRes);
          setPreviewError(null);
          if (previewRes.sheets.length > 0) {
            setActiveSheet((current) => current ?? previewRes.sheets[0].name);
          }
        } catch (err) {
          setPreview(null);
          setPreviewError(
            err instanceof Error ? err.message : t("reportPreviewLoadFailed"),
          );
        }
      }
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("reportLoadFailed"),
      );
    } finally {
      setLoading(false);
    }
  }, [id, t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleDownload() {
    if (!report) return;
    try {
      const fresh = await api.get<ReportExport>(
        `/recruitment/reports/${report.id}`,
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

  const sheets = useMemo(() => preview?.sheets ?? [], [preview]);

  return (
    <div className="space-y-6" data-testid="recruitment-report-detail-page">
      <RecruitmentBreadcrumbs
        segments={[
          { label: t("breadcrumbReports"), href: "/recruitment/reports" },
          {
            label: report
              ? report.template_name || t("reportBreadcrumbFallback")
              : t("loading"),
          },
        ]}
      />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {report?.template_name || t("reportDetailTitleFallback")}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {report ? (
              <>
                {t("reportDetailVacancyLabel")}{" "}
                <Link
                  className="hover:underline"
                  href={`/recruitment/requisitions/${report.vacancy_id}`}
                >
                  {report.vacancy_id}
                </Link>
              </>
            ) : (
              t("reportDetailLoadingDetails")
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {report && (
            <Badge
              variant="secondary"
              className={STATUS_COLORS[report.status] || ""}
              data-testid="recruitment-report-detail-status"
            >
              {report.status}
            </Badge>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => void refresh()}
            data-testid="recruitment-report-detail-btn-refresh"
          >
            <RefreshCw className="size-4" /> {t("actionRefresh")}
          </Button>
          <Button
            variant="default"
            size="sm"
            disabled={!report || report.status !== "completed"}
            onClick={() => void handleDownload()}
            data-testid="recruitment-report-detail-btn-download"
          >
            <Download className="size-4" /> {t("reportDownloadXlsx")}
          </Button>
        </div>
      </div>

      {report && (
        <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
          {report.sections.map((s: ReportSectionCode) => (
            <Badge key={s} variant="secondary">
              {reportSectionLabel(t, s)}
            </Badge>
          ))}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16 text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          <span className="ml-2">{t("loading")}</span>
        </div>
      ) : !report ? (
        <div className="rounded-lg border border-dashed p-12 text-center">
          <FileSpreadsheet className="mx-auto mb-3 h-10 w-10 text-muted-foreground opacity-40" />
          <p className="text-sm font-medium text-muted-foreground">
            {t("reportNotFound")}
          </p>
        </div>
      ) : report.status !== "completed" ? (
        <div className="rounded-lg border border-dashed p-12 text-center">
          <Loader2 className="mx-auto mb-3 h-10 w-10 animate-spin text-muted-foreground opacity-60" />
          <p className="text-sm font-medium text-muted-foreground">
            {report.status === "failed"
              ? t("reportBuildFailed", {
                  error: report.error || t("reportErrorUnknown"),
                })
              : t("reportStillGenerating")}
          </p>
        </div>
      ) : previewError ? (
        <div className="rounded-lg border border-dashed p-8 text-center">
          <p className="text-sm font-medium text-muted-foreground">
            {t("reportPreviewFailed", { error: previewError })}
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            {t("reportPreviewFailedHint")}
          </p>
        </div>
      ) : sheets.length === 0 ? (
        <div className="rounded-lg border border-dashed p-12 text-center">
          <p className="text-sm font-medium text-muted-foreground">
            {t("reportNoData")}
          </p>
        </div>
      ) : (
        <div
          className="space-y-3"
          data-testid="recruitment-report-detail-preview"
        >
          {preview?.truncated && (
            <p className="text-xs text-muted-foreground">
              {t("reportPreviewTruncated")}
            </p>
          )}
          <Tabs
            defaultValue={sheets[0].name}
            value={activeSheet ?? sheets[0].name}
            onValueChange={(value) => setActiveSheet(value)}
          >
            <TabsList className="flex-wrap">
              {sheets.map((sheet) => (
                <TabsTrigger key={sheet.name} value={sheet.name}>
                  {sheet.name}
                </TabsTrigger>
              ))}
            </TabsList>
            {sheets.map((sheet) => (
              <TabsContent key={sheet.name} value={sheet.name}>
                <div className="rounded-lg border overflow-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        {(sheet.cells[0] || []).map((cell, idx) => (
                          <TableHead key={idx}>{formatCell(cell)}</TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {sheet.cells.slice(1).map((row, rowIdx) => (
                        <TableRow key={rowIdx}>
                          {row.map((cell, cellIdx) => (
                            <TableCell key={cellIdx}>
                              {formatCell(cell)}
                            </TableCell>
                          ))}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </TabsContent>
            ))}
          </Tabs>
        </div>
      )}
    </div>
  );
}
