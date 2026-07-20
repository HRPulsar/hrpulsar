"use client";

import { useCallback, useEffect, useState } from "react";
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

const FIELDS: { key: keyof Retention; label: string; description: string }[] = [
  {
    key: "interviews_days",
    label: "Interview recordings (days)",
    description: "Audio, video, transcripts, AI analysis",
  },
  {
    key: "resumes_days",
    label: "Resumes (days)",
    description: "PDF/DOCX files and parsed structure",
  },
  {
    key: "consents_days",
    label: "Consents (days)",
    description: "ConsentRequest and candidate signatures",
  },
  {
    key: "reports_days",
    label: "XLSX reports (days)",
    description: "Generated vacancy summary reports",
  },
];

export default function RetentionPage() {
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
      toast.success("Retention periods updated");
      void load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error");
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
          { label: "Settings", href: "/recruitment/settings" },
          { label: "Data retention" },
        ]}
      />
      <header>
        <h1 className="text-xl font-semibold tracking-tight">
          Data retention periods
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          After the retention period expires, data is automatically anonymized
          (soft-erase). Changes take effect after the next cleanup cycle.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Policy</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {loading ? (
            <div className="flex items-center justify-center py-6 text-sm text-muted-foreground">
              <Loader2 className="mr-2 size-4 animate-spin" />
              Loading…
            </div>
          ) : (
            <>
              {FIELDS.map((f) => (
                <div className="grid gap-2 sm:grid-cols-[1fr_8rem]" key={f.key}>
                  <div className="space-y-0.5">
                    <Label htmlFor={`retention-${f.key}`}>{f.label}</Label>
                    <p className="text-xs text-muted-foreground">
                      {f.description}
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
                  Retention is less than 30 days. Make sure you have a legal
                  basis (for example, explicit candidate consent).
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
                  Save
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>
      {data && (
        <p className="text-xs text-muted-foreground">
          Current policy: interviews {data.interviews_days} d · resumes{" "}
          {data.resumes_days} d · consents {data.consents_days} d · reports{" "}
          {data.reports_days} d.
        </p>
      )}
    </div>
  );
}
