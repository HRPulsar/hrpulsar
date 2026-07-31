"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import {
  REPORT_SECTION_CODES,
  reportSectionLabel,
  type ReportSectionCode,
  type ReportTemplate,
  type ReportTemplateCreate,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Loader2, Plus, Save, Star, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { RecruitmentBreadcrumbs } from "@/components/recruitment";

const DEFAULT_SECTIONS: ReportSectionCode[] = [
  "vacancy_summary",
  "competence_profile",
  "candidates_summary",
  "comparison_grid",
  "interview_analysis",
];

export default function ReportTemplatesPage() {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [templates, setTemplates] = useState<ReportTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<{
    name: string;
    sections: ReportSectionCode[];
    is_default: boolean;
  }>({
    name: "",
    sections: DEFAULT_SECTIONS,
    is_default: false,
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api.get<ReportTemplate[]>(
        "/recruitment/report-templates",
      );
      setTemplates(rows);
    } catch {
      setTemplates([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function toggleDraftSection(code: ReportSectionCode) {
    setDraft((prev) => ({
      ...prev,
      sections: prev.sections.includes(code)
        ? prev.sections.filter((c) => c !== code)
        : [...prev.sections, code],
    }));
  }

  async function handleCreate() {
    if (!draft.name.trim()) {
      toast.error(t("reportTemplateNameRequired"));
      return;
    }
    if (draft.sections.length === 0) {
      toast.error(t("reportTemplateSectionRequired"));
      return;
    }
    setCreating(true);
    try {
      const body: ReportTemplateCreate = {
        name: draft.name.trim(),
        sections: draft.sections,
        is_default: draft.is_default,
        is_active: true,
      };
      await api.post<ReportTemplate>("/recruitment/report-templates", body);
      toast.success(t("reportTemplateToastCreated"));
      setDraft({ name: "", sections: DEFAULT_SECTIONS, is_default: false });
      void load();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("templateCreateFailed"),
      );
    } finally {
      setCreating(false);
    }
  }

  async function handleToggleActive(row: ReportTemplate) {
    setSavingId(row.id);
    try {
      await api.put<ReportTemplate>(`/recruitment/report-templates/${row.id}`, {
        is_active: !row.is_active,
      });
      void load();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("templateUpdateFailed"),
      );
    } finally {
      setSavingId(null);
    }
  }

  async function handleSetDefault(row: ReportTemplate) {
    setSavingId(row.id);
    try {
      await api.put<ReportTemplate>(`/recruitment/report-templates/${row.id}`, {
        is_default: true,
      });
      toast.success(t("reportTemplateToastDefault", { name: row.name }));
      void load();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("templateUpdateFailed"),
      );
    } finally {
      setSavingId(null);
    }
  }

  async function handleDelete(row: ReportTemplate) {
    if (!confirm(t("reportTemplateDeleteConfirm", { name: row.name }))) return;
    setSavingId(row.id);
    try {
      await api.delete(`/recruitment/report-templates/${row.id}`);
      void load();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("templateDeleteFailed"),
      );
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div className="space-y-6" data-testid="recruitment-report-templates-page">
      <RecruitmentBreadcrumbs
        segments={[
          { label: tc("settings"), href: "/recruitment/settings" },
          { label: t("reportTemplatesTitle") },
        ]}
      />

      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          {t("reportTemplatesTitle")}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("reportTemplatesDescription")}
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("reportTemplateCreateCardTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="rt-name">{t("fieldName")}</Label>
            <Input
              id="rt-name"
              value={draft.name}
              onChange={(e) =>
                setDraft((prev) => ({ ...prev, name: e.target.value }))
              }
              placeholder={t("reportTemplateNamePlaceholder")}
              data-testid="recruitment-report-template-name"
            />
          </div>
          <div className="space-y-2">
            <Label>{t("reportTemplateSectionsLabel")}</Label>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {REPORT_SECTION_CODES.map((code) => {
                const checked = draft.sections.includes(code);
                return (
                  <label
                    key={code}
                    className="flex items-start gap-2 rounded-md border border-border bg-card p-2 text-sm"
                  >
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => toggleDraftSection(code)}
                      data-testid={`recruitment-report-template-section-${code}`}
                    />
                    <span>{reportSectionLabel(t, code)}</span>
                  </label>
                );
              })}
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={draft.is_default}
              onCheckedChange={(v) =>
                setDraft((prev) => ({ ...prev, is_default: Boolean(v) }))
              }
            />
            {t("reportTemplateSetDefaultCheckbox")}
          </label>
          <div>
            <Button
              onClick={handleCreate}
              disabled={creating}
              data-testid="recruitment-report-template-btn-create"
            >
              {creating ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Plus className="size-4" />
              )}
              {t("actionCreate")}
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="space-y-3">
        <h2 className="text-lg font-semibold">{t("templatesExistingTitle")}</h2>
        {loading ? (
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            {t("loading")}
          </div>
        ) : templates.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("templatesEmpty")}</p>
        ) : (
          <div className="grid gap-3">
            {templates.map((row) => (
              <Card key={row.id}>
                <CardContent className="space-y-3 pt-6">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <h3 className="text-base font-semibold">{row.name}</h3>
                      {row.is_default && (
                        <Badge variant="default" className="gap-1">
                          <Star className="size-3" />{" "}
                          {t("reportTemplateBadgeDefault")}
                        </Badge>
                      )}
                      {!row.is_active && (
                        <Badge variant="secondary">
                          {t("reportTemplateBadgeInactive")}
                        </Badge>
                      )}
                    </div>
                    <div className="flex items-center gap-1">
                      {!row.is_default && (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={savingId === row.id}
                          onClick={() => handleSetDefault(row)}
                        >
                          <Star className="size-4" />{" "}
                          {t("reportTemplateMakeDefault")}
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={savingId === row.id}
                        onClick={() => handleToggleActive(row)}
                      >
                        <Save className="size-4" />
                        {row.is_active ? t("actionDisable") : t("actionEnable")}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={savingId === row.id}
                        onClick={() => handleDelete(row)}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {row.sections.length === 0 ? (
                      <span className="text-xs text-muted-foreground">
                        {t("reportTemplateNoSections")}
                      </span>
                    ) : (
                      row.sections.map((s) => (
                        <Badge key={s} variant="secondary" className="text-xs">
                          {reportSectionLabel(t, s)}
                        </Badge>
                      ))
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
