"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Download,
  FileSpreadsheet,
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { ReportWizardDialog } from "./report-wizard-dialog";
import { api } from "@/lib/api";
import {
  reportSectionLabel,
  reportStatusLabel,
  type ReportExport,
  type ReportExportList,
  type ReportSectionCode,
  type ReportStatus,
} from "@/lib/types";
import { toast } from "sonner";
import { formatDateTime } from "@/lib/date-format";
import { BADGE_COLOR } from "@/lib/badge-tones";

interface ReportsTabProps {
  vacancyId: string;
}

const STATUS_COLORS: Record<ReportStatus, string> = {
  pending: BADGE_COLOR.blue,
  processing: BADGE_COLOR.yellow,
  completed: BADGE_COLOR.green,
  failed: BADGE_COLOR.red,
};

export function ReportsTab({ vacancyId }: ReportsTabProps) {
  const t = useTranslations("recruitment");
  const [items, setItems] = useState<ReportExport[]>([]);
  const [loading, setLoading] = useState(true);
  const [wizardOpen, setWizardOpen] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<ReportExportList>(
        `/recruitment/vacancies/${vacancyId}/reports`,
      );
      setItems(res.items);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("reportsLoadFailed"));
    } finally {
      setLoading(false);
    }
  }, [vacancyId, t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const hasInflight = items.some(
    (it) => it.status === "pending" || it.status === "processing",
  );

  // Auto-refresh while a generation is in flight (a few rounds is enough —
  // the wizard polls inline; this covers the case where the wizard was
  // closed before completion).
  useEffect(() => {
    if (!hasInflight) return;
    const handle = setInterval(refresh, 3000);
    return () => clearInterval(handle);
  }, [hasInflight, refresh]);

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
        err instanceof Error ? err.message : t("reportsTabDownloadLinkFailed"),
      );
    }
  }

  return (
    <div className="space-y-4" data-testid="recruitment-reports-tab">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">{t("reportsTitle")}</h2>
          <p className="text-sm text-muted-foreground">
            {t("reportsTabDescription")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void refresh()}
            data-testid="recruitment-reports-btn-refresh"
          >
            <RefreshCw className="size-4" />
            {t("actionRefresh")}
          </Button>
          <Button
            size="sm"
            onClick={() => setWizardOpen(true)}
            data-testid="recruitment-reports-btn-new"
          >
            <Plus className="size-4" />
            {t("reportsTabGenerateButton")}
          </Button>
        </div>
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
          <p className="mt-1 text-xs text-muted-foreground">
            {t("reportsTabEmptyHint")}
          </p>
        </div>
      ) : (
        <div className="rounded-lg border">
          <Table data-testid="recruitment-reports-table">
            <TableHeader>
              <TableRow>
                <TableHead>{t("reportsColRequested")}</TableHead>
                <TableHead>{t("reportsColSections")}</TableHead>
                <TableHead>{t("columnStatus")}</TableHead>
                <TableHead>{t("reportsTabColReady")}</TableHead>
                <TableHead className="w-[160px] text-right">
                  {t("columnActions")}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((row) => (
                <TableRow
                  key={row.id}
                  data-testid={`recruitment-reports-row-${row.id}`}
                >
                  <TableCell>
                    <div className="text-sm font-medium">
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
                      {reportStatusLabel(t, row.status)}
                    </Badge>
                    {row.status === "failed" && row.error && (
                      <p
                        className="mt-1 max-w-[260px] truncate text-xs text-red-600"
                        title={row.error}
                      >
                        {row.error}
                      </p>
                    )}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {row.completed_at
                      ? formatDateTime(row.completed_at)
                      : "—"}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={row.status !== "completed"}
                        onClick={() => void handleDownload(row)}
                        data-testid={`recruitment-reports-btn-download-${row.id}`}
                      >
                        <Download className="size-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => void handleDelete(row.id)}
                        data-testid={`recruitment-reports-btn-delete-${row.id}`}
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

      <ReportWizardDialog
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        vacancyId={vacancyId}
        onCreated={() => {
          void refresh();
        }}
      />
    </div>
  );
}
