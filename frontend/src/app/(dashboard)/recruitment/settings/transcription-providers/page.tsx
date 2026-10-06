"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { KeyRound, Loader2, Plus, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { RecruitmentBreadcrumbs } from "@/components/recruitment";
import { RequireRole } from "@/components/require-role";
import { BADGE_COLOR } from "@/lib/badge-tones";

type Provider = {
  id: string;
  provider: string;
  api_key_masked: string | null;
  is_active: boolean;
  settings: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

// HRP-476: labels live in the `recruitment` i18n namespace; this map only
// owns the API code → key relation. HRP-985: only what the chain can run —
// a saved row of any other provider shows as unavailable, to be deleted.
const PROVIDERS = [
  { value: "whisper", labelKey: "sttProviderWhisper" },
  { value: "deepgram", labelKey: "sttProviderDeepgram" },
  { value: "assemblyai", labelKey: "sttProviderAssemblyai" },
  { value: "yandex_speechkit", labelKey: "sttProviderYandex" },
];
const isAvailable = (provider: string) =>
  PROVIDERS.some((p) => p.value === provider);

const EMPTY_DRAFT = {
  provider: "deepgram",
  api_key: "",
  folder_id: "",
  base_url: "",
};

export default function STTProvidersPage() {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [rows, setRows] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [draft, setDraft] = useState(EMPTY_DRAFT);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get<Provider[]>(
        "/recruitment/settings/transcription-providers",
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
    setCreating(true);
    // SpeechKit addresses the account by folder, so the key alone is not a
    // credential; Whisper may run on the workspace's own server (HRP-985).
    const settings: Record<string, string> = {};
    if (draft.provider === "yandex_speechkit" && draft.folder_id) {
      settings.folder_id = draft.folder_id;
    }
    if (draft.provider === "whisper" && draft.base_url.trim()) {
      settings.base_url = draft.base_url.trim();
    }
    try {
      await api.post("/recruitment/settings/transcription-providers", {
        provider: draft.provider,
        api_key: draft.api_key || null,
        is_active: true,
        settings: Object.keys(settings).length ? settings : null,
      });
      toast.success(t("sttToastAdded"));
      setDraft(EMPTY_DRAFT);
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
      await api.put(
        `/recruitment/settings/transcription-providers/${p.id}`,
        { is_active: !p.is_active },
      );
      void load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastGenericError"));
    } finally {
      setSavingId(null);
    }
  }

  // HRP-985: a Whisper row on the workspace's own server keeps the audio
  // there; platform providers take over only when this is switched on.
  async function handleFallback(p: Provider, allow: boolean) {
    setSavingId(p.id);
    try {
      await api.put(
        `/recruitment/settings/transcription-providers/${p.id}`,
        { settings: { ...p.settings, allow_platform_fallback: allow } },
      );
      void load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastGenericError"));
    } finally {
      setSavingId(null);
    }
  }

  async function handleDelete(p: Provider) {
    if (!confirm(t("sttDeleteConfirm", { provider: p.provider }))) return;
    setSavingId(p.id);
    try {
      await api.delete(
        `/recruitment/settings/transcription-providers/${p.id}`,
      );
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
    <div className="space-y-5" data-testid="recruitment-stt-providers-page">
      <RecruitmentBreadcrumbs
        segments={[
          { label: tc("settings"), href: "/recruitment/settings" },
          { label: t("sttBreadcrumb") },
        ]}
      />
      <header>
        <h1 className="text-xl font-semibold tracking-tight">
          {t("sttTitle")}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("sttDescription")}
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("sttAddCardTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="stt-provider">{t("llmProviderLabel")}</Label>
              <select
                id="stt-provider"
                value={draft.provider}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, provider: e.target.value }))
                }
                className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
                data-testid="stt-input-provider"
              >
                {PROVIDERS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {t(p.labelKey)}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="stt-key">{t("llmApiKeyLabel")}</Label>
              <Input
                id="stt-key"
                type="password"
                value={draft.api_key}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, api_key: e.target.value }))
                }
                placeholder="dg-… / sk-…"
                data-testid="stt-input-key"
              />
            </div>
            {draft.provider === "yandex_speechkit" ? (
              <div className="space-y-1">
                <Label htmlFor="stt-folder">{t("sttFolderIdLabel")}</Label>
                <Input
                  id="stt-folder"
                  value={draft.folder_id}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, folder_id: e.target.value }))
                  }
                  placeholder="b1g…"
                  data-testid="stt-input-folder"
                />
                <p className="text-xs text-muted-foreground">
                  {t("sttFolderIdHint")}
                </p>
              </div>
            ) : null}
            {draft.provider === "whisper" ? (
              <div className="space-y-1">
                <Label htmlFor="stt-base-url">{t("sttBaseUrlLabel")}</Label>
                <Input
                  id="stt-base-url"
                  type="url"
                  value={draft.base_url}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, base_url: e.target.value }))
                  }
                  placeholder="https://api.openai.com/v1"
                  data-testid="stt-input-base-url"
                />
                <p className="text-xs text-muted-foreground">
                  {t("sttBaseUrlHint")}
                </p>
              </div>
            ) : null}
          </div>
          <div className="flex justify-end">
            <Button
              onClick={handleCreate}
              disabled={creating}
              data-testid="stt-btn-create"
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
            {t("sttEmpty")}
          </div>
        ) : (
          <ul className="space-y-2">
            {rows.map((p) => (
              <li
                key={p.id}
                className="flex items-center justify-between gap-2 rounded-lg border p-3"
                data-testid={`stt-row-${p.id}`}
              >
                <div className="flex flex-col gap-0.5">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium capitalize">
                      {p.provider}
                    </span>
                    {!isAvailable(p.provider) ? (
                      <Badge variant="outline">
                        {t("sttStatusUnavailable")}
                      </Badge>
                    ) : p.is_active ? (
                      <Badge className={BADGE_COLOR.emerald}>
                        {t("statusActive")}
                      </Badge>
                    ) : (
                      <Badge variant="outline">{t("statusDisabled")}</Badge>
                    )}
                  </div>
                  {isAvailable(p.provider) ? (
                    <span className="flex items-center gap-1 text-xs text-muted-foreground">
                      <KeyRound className="size-3" />
                      {p.api_key_masked || t("providerKeyNotSet")}
                      {typeof p.settings?.base_url === "string"
                        ? ` · ${p.settings.base_url}`
                        : null}
                    </span>
                  ) : (
                    <span className="text-xs text-muted-foreground">
                      {t("sttUnavailableHint")}
                    </span>
                  )}
                  {p.provider === "whisper" &&
                  typeof p.settings?.base_url === "string" ? (
                    <label
                      className="flex items-center gap-1.5 text-xs text-muted-foreground"
                      title={t("sttPlatformFallbackHint")}
                    >
                      <Checkbox
                        checked={p.settings?.allow_platform_fallback === true}
                        onCheckedChange={(v) => handleFallback(p, v === true)}
                        disabled={savingId === p.id}
                        data-testid={`stt-checkbox-platform-fallback-${p.id}`}
                      />
                      {t("sttPlatformFallbackLabel")}
                    </label>
                  ) : null}
                </div>
                <div className="flex items-center gap-1">
                  {/* The API refuses any edit of an unavailable row; delete only. */}
                  {isAvailable(p.provider) ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => handleToggle(p)}
                      disabled={savingId === p.id}
                      data-testid={`stt-btn-toggle-${p.id}`}
                    >
                      <Save className="size-3.5" />
                      {p.is_active ? t("actionDisable") : t("actionEnable")}
                    </Button>
                  ) : null}
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleDelete(p)}
                    disabled={savingId === p.id}
                    data-testid={`stt-btn-delete-${p.id}`}
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
