"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Loader2, KeyRound, PlugZap, Plus, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { RecruitmentBreadcrumbs } from "@/components/recruitment";
import { RequireRole } from "@/components/require-role";
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

// Suggested model per provider. Switching providers replaces a model that
// belongs to another one — the backend rejects such pairs (HRP-498), and
// silently saved mismatches used to break the whole recruitment pipeline.
const DEFAULT_MODELS: Record<string, string> = {
  anthropic: "claude-sonnet-5",
  openai: "gpt-4o",
  gemini: "gemini-2.5-pro",
  yandex: "yandexgpt",
};

// Mirrors ai.providers.classify_model / PROVIDER_ALIASES: a name no
// provider claims by prefix (local servers) belongs to whoever is picked.
// Yandex model URIs ("gpt://...") must be checked before the OpenAI
// prefixes — longest match wins, as on the backend (HRP-599).
function modelOwner(model: string): string | null {
  if (model.startsWith("claude")) return "anthropic";
  if (model.startsWith("gpt://") || model.startsWith("yandexgpt"))
    return "yandex";
  if (/^(gpt|o1|o3|o4|text-embedding)/.test(model)) return "openai";
  if (model.startsWith("gemini")) return "gemini";
  return null;
}

// Providers that speak the OpenAI API: a base_url points them at a
// self-hosted server (Ollama, vLLM). It lives in the row's `settings`, and a
// key is optional there (HRP-986).
const BASE_URL_PROVIDERS = new Set(["openai", "azure", "gigachat"]);
// Azure and GigaChat are reached only through their own endpoint: without
// an address the row is never used, and the API refuses it.
const BASE_URL_REQUIRED = new Set(["azure", "gigachat"]);

function rowBaseUrl(p: Provider): string | null {
  const raw = p.settings?.base_url;
  return typeof raw === "string" && raw ? raw : null;
}

function canonicalProvider(provider: string): string {
  if (provider === "azure" || provider === "gigachat")
    return "openai_compatible";
  return provider;
}

export default function LLMProvidersPage() {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [rows, setRows] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [draft, setDraft] = useState({
    provider: "anthropic",
    model: "claude-sonnet-5",
    api_key: "",
    base_url: "",
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
    const baseUrl = BASE_URL_PROVIDERS.has(draft.provider)
      ? draft.base_url.trim()
      : "";
    if (BASE_URL_REQUIRED.has(draft.provider) && !baseUrl) {
      toast.error(t("llmBaseUrlRequired"));
      return;
    }
    setCreating(true);
    try {
      await api.post("/recruitment/settings/llm-providers", {
        provider: draft.provider,
        model: draft.model,
        api_key: draft.api_key || null,
        is_active: true,
        settings: baseUrl ? { base_url: baseUrl } : null,
      });
      toast.success(t("llmToastAdded"));
      setDraft({
        provider: "anthropic",
        model: "claude-sonnet-5",
        api_key: "",
        base_url: "",
      });
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

  // One tiny call through this row's own key/server/model (HRP-986); the
  // backend answers ok or a localized reason.
  async function handleTest(p: Provider) {
    setTestingId(p.id);
    try {
      await api.post(`/recruitment/settings/llm-providers/${p.id}/test`);
      toast.success(t("llmTestOk"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastGenericError"));
    } finally {
      setTestingId(null);
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

  // The whole provider registry is `require_role("admin")` on the API —
  // reads included, so a recruiter saw an empty page and a 403 toast.
  return (
    <RequireRole admin>
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
                  setDraft((d) => {
                    const provider = e.target.value;
                    const owner = modelOwner(d.model);
                    const keepModel =
                      owner === null || owner === canonicalProvider(provider);
                    return {
                      ...d,
                      provider,
                      model: keepModel
                        ? d.model
                        : (DEFAULT_MODELS[provider] ?? ""),
                    };
                  })
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
          {BASE_URL_PROVIDERS.has(draft.provider) && (
            <div className="space-y-1">
              <Label htmlFor="llm-base-url">{t("llmBaseUrlLabel")}</Label>
              <Input
                id="llm-base-url"
                type="url"
                value={draft.base_url}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, base_url: e.target.value }))
                }
                placeholder="http://localhost:11434/v1"
                required={BASE_URL_REQUIRED.has(draft.provider)}
                data-testid="llm-input-base-url"
              />
              <p className="text-xs text-muted-foreground">
                {t("llmBaseUrlHint")}
                {draft.provider === "openai" && ` ${t("llmBaseUrlHintOpenai")}`}
              </p>
            </div>
          )}
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
                  {rowBaseUrl(p) && (
                    <span
                      className="break-all text-xs text-muted-foreground"
                      data-testid={`llm-row-base-url-${p.id}`}
                    >
                      {rowBaseUrl(p)}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => handleTest(p)}
                    disabled={testingId === p.id}
                    data-testid={`llm-btn-test-${p.id}`}
                  >
                    {testingId === p.id ? (
                      <Loader2 className="size-3.5 animate-spin" />
                    ) : (
                      <PlugZap className="size-3.5" />
                    )}
                    {t("llmTestButton")}
                  </Button>
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
    </RequireRole>
  );
}
