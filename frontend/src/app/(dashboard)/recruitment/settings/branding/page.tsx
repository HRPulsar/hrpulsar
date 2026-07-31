"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Loader2, Save } from "lucide-react";
import { toast } from "sonner";
import { RecruitmentBreadcrumbs } from "@/components/recruitment";

type Branding = {
  logo_file_id: string | null;
  logo_url: string | null;
  accent_color: string | null;
  secondary_color: string | null;
  watermark_text: string | null;
  raw: Record<string, string> | null;
};

export default function BrandingPage() {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [branding, setBranding] = useState<Branding | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState({
    accent_color: "",
    secondary_color: "",
    watermark_text: "",
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get<Branding>("/recruitment/settings/branding");
      setBranding(data);
      setDraft({
        accent_color: data.accent_color || "",
        secondary_color: data.secondary_color || "",
        watermark_text: data.watermark_text || "",
      });
    } catch {
      setBranding(null);
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
      await api.put<Branding>("/recruitment/settings/branding", {
        accent_color: draft.accent_color || null,
        secondary_color: draft.secondary_color || null,
        watermark_text: draft.watermark_text || null,
      });
      toast.success(t("brandingToastSaved"));
      void load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastGenericError"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-5" data-testid="recruitment-branding-page">
      <RecruitmentBreadcrumbs
        segments={[
          { label: tc("settings"), href: "/recruitment/settings" },
          { label: t("brandingBreadcrumb") },
        ]}
      />
      <header>
        <h1 className="text-xl font-semibold tracking-tight">
          {t("brandingTitle")}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("brandingDescription")}
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{tc("settings")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {loading ? (
            <div className="flex items-center justify-center py-6 text-sm text-muted-foreground">
              <Loader2 className="mr-2 size-4 animate-spin" />
              {t("loading")}
            </div>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1">
                  <Label htmlFor="brand-accent">{t("brandingAccentColor")}</Label>
                  <div className="flex items-center gap-2">
                    <Input
                      id="brand-accent"
                      type="color"
                      value={draft.accent_color || "#0066ff"}
                      onChange={(e) =>
                        setDraft((d) => ({
                          ...d,
                          accent_color: e.target.value,
                        }))
                      }
                      className="h-8 w-16 cursor-pointer"
                      data-testid="brand-input-accent"
                    />
                    <Input
                      value={draft.accent_color}
                      onChange={(e) =>
                        setDraft((d) => ({
                          ...d,
                          accent_color: e.target.value,
                        }))
                      }
                      placeholder="#0066ff"
                      className="h-8"
                    />
                  </div>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="brand-secondary">{t("brandingSecondaryColor")}</Label>
                  <div className="flex items-center gap-2">
                    <Input
                      id="brand-secondary"
                      type="color"
                      value={draft.secondary_color || "#1a1f36"}
                      onChange={(e) =>
                        setDraft((d) => ({
                          ...d,
                          secondary_color: e.target.value,
                        }))
                      }
                      className="h-8 w-16 cursor-pointer"
                    />
                    <Input
                      value={draft.secondary_color}
                      onChange={(e) =>
                        setDraft((d) => ({
                          ...d,
                          secondary_color: e.target.value,
                        }))
                      }
                      placeholder="#1a1f36"
                      className="h-8"
                    />
                  </div>
                </div>
              </div>
              <div className="space-y-1">
                <Label htmlFor="brand-watermark">{t("brandingWatermark")}</Label>
                <Input
                  id="brand-watermark"
                  value={draft.watermark_text}
                  onChange={(e) =>
                    setDraft((d) => ({
                      ...d,
                      watermark_text: e.target.value,
                    }))
                  }
                  placeholder={t("brandingWatermarkPlaceholder")}
                  data-testid="brand-input-watermark"
                />
              </div>
              <div className="flex justify-end">
                <Button
                  onClick={handleSave}
                  disabled={saving}
                  data-testid="brand-btn-save"
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

      {branding && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("brandingPreviewTitle")}</CardTitle>
          </CardHeader>
          <CardContent>
            <div
              className="flex h-24 items-center justify-between rounded-lg border p-4"
              style={{
                background: draft.accent_color || "#0066ff",
                color: "#fff",
              }}
            >
              <div>
                <div className="text-sm font-semibold">
                  {t("brandingPreviewReportLabel")}
                </div>
                <div className="text-xs opacity-80">
                  {draft.watermark_text || "—"}
                </div>
              </div>
              <div
                className="rounded bg-white/20 px-3 py-1 text-xs uppercase tracking-wide"
              >
                XLSX
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
