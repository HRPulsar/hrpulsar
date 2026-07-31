"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Loader2, KeyRound, Plus, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { RecruitmentBreadcrumbs } from "@/components/recruitment";
import { BADGE_COLOR } from "@/lib/badge-tones";

type Provider = {
  id: string;
  provider: string;
  model: string;
  api_key_masked: string | null;
  is_active: boolean;
  settings: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

// HRP-476: labels live in the `recruitment` i18n namespace; this map only
// owns the API code → key relation.
const PROVIDERS = [
  { value: "anthropic", labelKey: "llmProviderAnthropic" },
  { value: "openai", labelKey: "llmProviderOpenai" },
  { value: "gemini", labelKey: "llmProviderGemini" },
  { value: "azure", labelKey: "llmProviderAzure" },
  { value: "yandex", labelKey: "llmProviderYandex" },
  { value: "gigachat", labelKey: "llmProviderGigachat" },
];

export default function LLMProvidersPage() {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [rows, setRows] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [draft, setDraft] = useState({
    provider: "anthropic",
    model: "claude-sonnet-5",
    api_key: "",
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get<Provider[]>(
        "/recruitment/settings/llm-providers",
      );
      setRows(data);
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreate() {
    if (!draft.model.trim()) {
      toast.error(t("llmModelRequired"));
      return;
    }
    setCreating(true);
    try {
      await api.post("/recruitment/settings/llm-providers", {
        provider: draft.provider,
        model: draft.model,
        api_key: draft.api_key || null,
        is_active: true,
      });
      toast.success(t("llmToastAdded"));
      setDraft({ provider: "anthropic", model: "claude-sonnet-5", api_key: "" });
      void load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastGenericError"));
    } finally {
      setCreating(false);
    }
  }

  async function handleToggle(p: Provider) {
    setSavingId(p.id);
    try {
      await api.put(`/recruitment/settings/llm-providers/${p.id}`, {
        is_active: !p.is_active,
      });
      void load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastGenericError"));
    } finally {
      setSavingId(null);
    }
  }

  async function handleDelete(p: Provider) {
    if (
      !confirm(t("llmDeleteConfirm", { provider: p.provider, model: p.model }))
    )
      return;
    setSavingId(p.id);
    try {
      await api.delete(`/recruitment/settings/llm-providers/${p.id}`);
      void load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastGenericError"));
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div className="space-y-5" data-testid="recruitment-llm-providers-page">
      <RecruitmentBreadcrumbs
        segments={[
          { label: tc("settings"), href: "/recruitment/settings" },
          { label: t("llmBreadcrumb") },
        ]}
      />
      <header>
        <h1 className="text-xl font-semibold tracking-tight">
          {t("llmTitle")}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("llmDescription")}
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("llmAddCardTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1">
              <Label htmlFor="llm-provider">{t("llmProviderLabel")}</Label>
              <select
                id="llm-provider"
                value={draft.provider}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, provider: e.target.value }))
                }
                className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
                data-testid="llm-input-provider"
              >
                {PROVIDERS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {t(p.labelKey)}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="llm-model">{t("llmModelLabel")}</Label>
              <Input
                id="llm-model"
                value={draft.model}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, model: e.target.value }))
                }
                placeholder="claude-sonnet-5"
                data-testid="llm-input-model"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="llm-key">{t("llmApiKeyLabel")}</Label>
              <Input
                id="llm-key"
                type="password"
                value={draft.api_key}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, api_key: e.target.value }))
                }
                placeholder="sk-…"
                data-testid="llm-input-key"
              />
            </div>
          </div>
          <div className="flex justify-end">
            <Button
              onClick={handleCreate}
              disabled={creating}
              data-testid="llm-btn-create"
            >
              {creating ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Plus className="size-4" />
              )}
              {t("llmAddButton")}
            </Button>
          </div>
        </CardContent>
      </Card>

      <section className="space-y-2">
        <h2 className="text-sm font-medium">{t("llmConnectedTitle")}</h2>
        {loading ? (
          <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin" />
            {t("loading")}
          </div>
        ) : rows.length === 0 ? (
          <div className="rounded-md border border-dashed p-6 text-center text-xs text-muted-foreground">
            {t("llmEmpty")}
          </div>
        ) : (
          <ul className="space-y-2">
            {rows.map((p) => (
              <li
                key={p.id}
                className="flex items-center justify-between gap-2 rounded-lg border p-3"
                data-testid={`llm-row-${p.id}`}
              >
                <div className="flex flex-col gap-0.5">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium capitalize">
                      {p.provider}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {p.model}
                    </span>
                    {p.is_active ? (
                      <Badge className={BADGE_COLOR.emerald}>
                        {t("statusActive")}
                      </Badge>
                    ) : (
                      <Badge variant="outline">{t("statusDisabled")}</Badge>
                    )}
                  </div>
                  <span className="flex items-center gap-1 text-xs text-muted-foreground">
                    <KeyRound className="size-3" />
                    {p.api_key_masked || t("providerKeyNotSet")}
                  </span>
                </div>
                <div className="flex items-center gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => handleToggle(p)}
                    disabled={savingId === p.id}
                    data-testid={`llm-btn-toggle-${p.id}`}
                  >
                    <Save className="size-3.5" />
                    {p.is_active ? t("actionDisable") : t("actionEnable")}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleDelete(p)}
                    disabled={savingId === p.id}
                    data-testid={`llm-btn-delete-${p.id}`}
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
