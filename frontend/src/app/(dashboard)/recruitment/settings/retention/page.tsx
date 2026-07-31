"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AlertTriangle, Loader2, Save } from "lucide-react";
import { toast } from "sonner";
import { RecruitmentBreadcrumbs } from "@/components/recruitment";
import { ALERT_TONE } from "@/lib/badge-tones";

type Retention = {
  interviews_days: number;
  resumes_days: number;
  consents_days: number;
  reports_days: number;
};

// HRP-476: the field copy lives in the `recruitment` i18n namespace — the
// static list only owns the payload key → key relation.
const FIELDS: {
  key: keyof Retention;
  labelKey: string;
  descriptionKey: string;
}[] = [
  {
    key: "interviews_days",
    labelKey: "retentionFieldInterviews",
    descriptionKey: "retentionFieldInterviewsDesc",
  },
  {
    key: "resumes_days",
    labelKey: "retentionFieldResumes",
    descriptionKey: "retentionFieldResumesDesc",
  },
  {
    key: "consents_days",
    labelKey: "retentionFieldConsents",
    descriptionKey: "retentionFieldConsentsDesc",
  },
  {
    key: "reports_days",
    labelKey: "retentionFieldReports",
    descriptionKey: "retentionFieldReportsDesc",
  },
];

export default function RetentionPage() {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [data, setData] = useState<Retention | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState<Retention>({
    interviews_days: 365,
    resumes_days: 365,
    consents_days: 365,
    reports_days: 365,
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.get<Retention>(
        "/recruitment/settings/retention",
      );
      setData(result);
      setDraft(result);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleSave() {
    setSaving(true);
    try {
      await api.put<Retention>("/recruitment/settings/retention", draft);
      toast.success(t("retentionToastSaved"));
      void load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastGenericError"));
    } finally {
      setSaving(false);
    }
  }

  const hasShortRetention = Object.values(draft).some(
    (v) => typeof v === "number" && v < 30,
  );

  return (
    <div className="space-y-5" data-testid="recruitment-retention-page">
      <RecruitmentBreadcrumbs
        segments={[
          { label: tc("settings"), href: "/recruitment/settings" },
          { label: t("retentionBreadcrumb") },
        ]}
      />
      <header>
        <h1 className="text-xl font-semibold tracking-tight">
          {t("retentionTitle")}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("retentionDescription")}
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("retentionPolicyCardTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {loading ? (
            <div className="flex items-center justify-center py-6 text-sm text-muted-foreground">
              <Loader2 className="mr-2 size-4 animate-spin" />
              {t("loading")}
            </div>
          ) : (
            <>
              {FIELDS.map((f) => (
                <div className="grid gap-2 sm:grid-cols-[1fr_8rem]" key={f.key}>
                  <div className="space-y-0.5">
                    <Label htmlFor={`retention-${f.key}`}>
                      {t(f.labelKey)}
                    </Label>
                    <p className="text-xs text-muted-foreground">
                      {t(f.descriptionKey)}
                    </p>
                  </div>
                  <Input
                    id={`retention-${f.key}`}
                    type="number"
                    min={1}
                    max={3650}
                    value={draft[f.key]}
                    onChange={(e) =>
                      setDraft((d) => ({
                        ...d,
                        [f.key]: Number(e.target.value),
                      }))
                    }
                    data-testid={`retention-input-${f.key}`}
                  />
                </div>
              ))}
              {hasShortRetention && (
                <div className={`flex gap-2 rounded-md border p-2 text-xs ${ALERT_TONE.amber}`}>
                  <AlertTriangle className="size-4 shrink-0" />
                  {t("retentionShortWarning")}
                </div>
              )}
              <div className="flex justify-end">
                <Button
                  onClick={handleSave}
                  disabled={saving}
                  data-testid="retention-btn-save"
                >
                  {saving ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <Save className="size-4" />
                  )}
                  {t("save")}
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>
      {data && (
        <p className="text-xs text-muted-foreground">
          {t("retentionCurrentPolicy", {
            interviews: String(data.interviews_days),
            resumes: String(data.resumes_days),
            consents: String(data.consents_days),
            reports: String(data.reports_days),
          })}
        </p>
      )}
    </div>
  );
}
