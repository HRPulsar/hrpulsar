"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  REPORT_SECTION_CODES,
  REPORT_SECTION_LABELS,
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
      toast.error("Provide a template name");
      return;
    }
    if (draft.sections.length === 0) {
      toast.error("Select at least one section");
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
      toast.success("Template created");
      setDraft({ name: "", sections: DEFAULT_SECTIONS, is_default: false });
      void load();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to create template",
      );
    } finally {
      setCreating(false);
    }
  }

  async function handleToggleActive(t: ReportTemplate) {
    setSavingId(t.id);
    try {
      await api.put<ReportTemplate>(`/recruitment/report-templates/${t.id}`, {
        is_active: !t.is_active,
      });
      void load();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to update template",
      );
    } finally {
      setSavingId(null);
    }
  }

  async function handleSetDefault(t: ReportTemplate) {
    setSavingId(t.id);
    try {
      await api.put<ReportTemplate>(`/recruitment/report-templates/${t.id}`, {
        is_default: true,
      });
      toast.success(`"${t.name}" is now the default template`);
      void load();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to update template",
      );
    } finally {
      setSavingId(null);
    }
  }

  async function handleDelete(t: ReportTemplate) {
    if (!confirm(`Delete template "${t.name}"?`)) return;
    setSavingId(t.id);
    try {
      await api.delete(`/recruitment/report-templates/${t.id}`);
      void load();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to delete template",
      );
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div className="space-y-6" data-testid="recruitment-report-templates-page">
      <RecruitmentBreadcrumbs
        segments={[
          { label: "Settings", href: "/recruitment/settings" },
          { label: "Report templates" },
        ]}
      />

      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Report templates
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          A template defines which sections appear in the XLSX. One of them can
          be marked &ldquo;default&rdquo; — it will be pre-selected in the wizard.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Create template</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="rt-name">Name</Label>
            <Input
              id="rt-name"
              value={draft.name}
              onChange={(e) =>
                setDraft((prev) => ({ ...prev, name: e.target.value }))
              }
              placeholder="Standard hiring report"
              data-testid="recruitment-report-template-name"
            />
          </div>
          <div className="space-y-2">
            <Label>Sections</Label>
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
                    <span>{REPORT_SECTION_LABELS[code]}</span>
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
            Set as default template
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
              Create
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="space-y-3">
        <h2 className="text-lg font-semibold">Existing templates</h2>
        {loading ? (
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            Loading…
          </div>
        ) : templates.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No templates yet. Create your first one above.
          </p>
        ) : (
          <div className="grid gap-3">
            {templates.map((t) => (
              <Card key={t.id}>
                <CardContent className="space-y-3 pt-6">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <h3 className="text-base font-semibold">{t.name}</h3>
                      {t.is_default && (
                        <Badge variant="default" className="gap-1">
                          <Star className="size-3" /> default
                        </Badge>
                      )}
                      {!t.is_active && (
                        <Badge variant="secondary">inactive</Badge>
                      )}
                    </div>
                    <div className="flex items-center gap-1">
                      {!t.is_default && (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={savingId === t.id}
                          onClick={() => handleSetDefault(t)}
                        >
                          <Star className="size-4" /> Default
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={savingId === t.id}
                        onClick={() => handleToggleActive(t)}
                      >
                        <Save className="size-4" />
                        {t.is_active ? "Disable" : "Enable"}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={savingId === t.id}
                        onClick={() => handleDelete(t)}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {t.sections.length === 0 ? (
                      <span className="text-xs text-muted-foreground">
                        No sections
                      </span>
                    ) : (
                      t.sections.map((s) => (
                        <Badge key={s} variant="secondary" className="text-xs">
                          {REPORT_SECTION_LABELS[s] || s}
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
