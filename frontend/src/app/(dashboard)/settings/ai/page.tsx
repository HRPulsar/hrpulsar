"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { RequireRole } from "@/components/require-role";
import { useIsSaas } from "@/hooks/use-is-saas";
import { api } from "@/lib/api";
import {
  aiSettingsApi,
  CONTENT_LANGUAGES,
  type AISettings,
  type AllowedModel,
  type ContentLanguage,
  type EffortLevel,
  type EffortPreset,
  type LLMProvider,
  type ProviderStatus,
} from "@/lib/api/ai-settings";
import { localeLabel } from "@/lib/locale";
import {
  buildPatchDiff,
  isFormValid,
  roundUpTenth,
  settingsToForm,
  type AISettingsFormState as FormState,
} from "@/lib/ai-settings-form";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

const USE_PRESET_DEFAULT = "__preset__";

/** Preset name → key in the `settings` message namespace. */
const PRESET_LABEL_KEY: Record<Exclude<EffortLevel, "custom">, string> = {
  fast: "aiPresetFast",
  balanced: "aiPresetBalanced",
  thorough: "aiPresetThorough",
};

// i18n F7: the tier descriptions the API returns are static English
// copy from the PRESETS table — render the localized catalog strings
// instead.
const PRESET_DESCRIPTION_KEY: Record<Exclude<EffortLevel, "custom">, string> = {
  fast: "aiPresetFastDescription",
  balanced: "aiPresetBalancedDescription",
  thorough: "aiPresetThoroughDescription",
};

function formatMultiplier(value: number): string {
  return `×${value % 1 === 0 ? value.toFixed(1) : value.toString()}`;
}

// HRP-436: every Admin-section page denies access the same way — an error
// toast plus a redirect to the dashboard — instead of an inline panel.
export default function AISettingsPage() {
  return (
    <RequireRole admin>
      <AISettingsPageContent />
    </RequireRole>
  );
}

function AISettingsPageContent() {
  const t = useTranslations("settings");
  const isSaas = useIsSaas();
  const [settings, setSettings] = useState<AISettings | null>(null);
  const [presets, setPresets] = useState<EffortPreset[]>([]);
  const [models, setModels] = useState<AllowedModel[]>([]);
  const [costMap, setCostMap] = useState<Record<string, number>>({});
  const [form, setForm] = useState<FormState | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [providerFilter, setProviderFilter] = useState<string>("anthropic");
  const [providers, setProviders] = useState<ProviderStatus[]>([]);

  useEffect(() => {
    // RequireRole above guarantees an admin, so no in-effect role check.
    Promise.all([
      aiSettingsApi.get(),
      aiSettingsApi.presets(),
      aiSettingsApi.models(),
      aiSettingsApi.providers().catch(() => null),
      isSaas ? api.get<unknown>("/billing/costs").catch(() => null) : null,
    ])
      .then(([s, p, m, provs, costs]) => {
        setSettings(s);
        setPresets(p);
        setModels(m);
        if (provs) setProviders(provs.filter((x) => x.configured));
        setForm(settingsToForm(s));
        setProviderFilter(s.effective_provider);
        if (Array.isArray(costs)) {
          const flat: Record<string, number> = {};
          for (const cat of costs as Array<{
            actions: Array<{ action: string; cost: number }>;
          }>) {
            for (const a of cat.actions ?? []) flat[a.action] = a.cost;
          }
          setCostMap(flat);
        }
      })
      .catch((err) => {
        toast.error(
          err instanceof Error ? err.message : t("aiLoadFailed"),
        );
      })
      .finally(() => setLoading(false));
  }, [isSaas, t]);

  const baseForm = useMemo(
    () => (settings ? settingsToForm(settings) : null),
    [settings],
  );

  const diff = useMemo(() => {
    if (!baseForm || !form) return null;
    const patch = buildPatchDiff(baseForm, form);
    return Object.keys(patch).length > 0 ? patch : null;
  }, [baseForm, form]);

  const formValid = form ? isFormValid(form) : false;

  // Providers the tenant can actually generate through (HRP-465). Falls
  // back to the classic trio while loading or if the endpoint errors.
  // Brand labels stay verbatim; only the local-server option carries
  // translatable words, so it resolves through the catalog.
  const providerOptions = useMemo<Array<{ provider: string; label: string }>>(
    () =>
      (providers.length > 0
        ? providers
        : [
            { provider: "anthropic", label: "Anthropic" },
            { provider: "openai", label: "OpenAI" },
            { provider: "gemini", label: "Google" },
          ]
      ).map((p) =>
        p.provider === "openai_compatible"
          ? { ...p, label: t("aiProviderOpenAiCompatible") }
          : p,
      ),
    [providers, t],
  );

  // Preview multiplier of the *form* state (not yet saved).
  const previewMultiplier = useMemo(() => {
    if (!form) return 1.0;
    if (form.llm_model) {
      const entry = models.find((m) => m.model === form.llm_model);
      return entry?.credit_multiplier ?? 1.0;
    }
    // Preset default → take the model that matches the active provider in
    // the chosen preset, fall back to balanced.
    const preset = presets.find(
      (p) => p.name === (form.effort_level === "custom" ? "balanced" : form.effort_level),
    );
    const presetModel = preset?.models[providerFilter as LLMProvider];
    if (!presetModel) return 1.0;
    const entry = models.find((m) => m.model === presetModel);
    return entry?.credit_multiplier ?? 1.0;
  }, [form, models, presets, providerFilter]);

  if (loading || !settings || !form) {
    return (
      <div className="mx-auto max-w-3xl py-12 text-center text-sm text-muted-foreground">
        {t("aiLoading")}
      </div>
    );
  }

  function selectPreset(name: EffortLevel) {
    if (!form) return;
    setForm({ ...form, effort_level: name });
  }

  function setCustomField<K extends keyof FormState>(
    key: K,
    value: FormState[K],
  ) {
    if (!form) return;
    const flipsToCustom =
      key === "llm_model" || key === "temperature" || key === "max_retries";
    setForm({
      ...form,
      [key]: value,
      ...(flipsToCustom && form.effort_level !== "custom"
        ? { effort_level: "custom" as EffortLevel }
        : {}),
    });
  }

  async function handleSave() {
    if (!diff || !formValid) return;
    setSaving(true);
    try {
      const updated = await aiSettingsApi.update(diff);
      setSettings(updated);
      setForm(settingsToForm(updated));
      setProviderFilter(updated.effective_provider);
      toast.success(t("aiSaved"));
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("aiSaveFailed"),
      );
    } finally {
      setSaving(false);
    }
  }

  function handleDiscard() {
    if (!baseForm) return;
    setForm(baseForm);
  }

  async function handleReset() {
    setResetting(true);
    try {
      const updated = await aiSettingsApi.reset();
      setSettings(updated);
      setForm(settingsToForm(updated));
      setProviderFilter(updated.effective_provider);
      toast.success(t("aiResetDone"));
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("aiResetFailed"),
      );
    } finally {
      setResetting(false);
    }
  }

  const presetsByName = new Map(presets.map((p) => [p.name, p]));
  const modelsForProvider = models.filter(
    (m) => m.provider === providerFilter,
  );

  // Multiplier shown in each preset card uses the active provider's model.
  function presetMultiplier(name: Exclude<EffortLevel, "custom">): number {
    const preset = presetsByName.get(name);
    if (!preset) return 1.0;
    const presetModel = preset.models[providerFilter as LLMProvider];
    return models.find((m) => m.model === presetModel)?.credit_multiplier ?? 1.0;
  }

  const sampleCost = costMap["ai.generate_competences"];
  const currentSpend = sampleCost
    ? roundUpTenth(sampleCost * settings.effective_credit_multiplier)
    : null;
  const previewSpend = sampleCost
    ? roundUpTenth(sampleCost * previewMultiplier)
    : null;
  const showSpendPreview =
    sampleCost !== undefined &&
    currentSpend !== null &&
    previewSpend !== null &&
    Math.abs(currentSpend - previewSpend) > 0.001;

  return (
    <div className="mx-auto max-w-3xl space-y-6 pb-24">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{t("aiTitle")}</h1>
        <p className="text-sm text-muted-foreground">{t("aiDescription")}</p>
      </div>

      {/* Effort tier */}
      <Card>
        <CardHeader>
          <CardTitle>{t("aiEffortTier")}</CardTitle>
          <CardDescription>{t("aiEffortTierDescription")}</CardDescription>
        </CardHeader>
        <CardContent
          className="grid gap-3 sm:grid-cols-3"
          data-testid="settings-ai-presets"
        >
          {(["fast", "balanced", "thorough"] as const).map((name) => {
            const preset = presetsByName.get(name);
            const active = form.effort_level === name;
            const mult = presetMultiplier(name);
            return (
              <button
                key={name}
                type="button"
                onClick={() => selectPreset(name)}
                data-testid={`settings-ai-preset-${name}`}
                data-active={active ? "true" : undefined}
                className={cn(
                  "rounded-md border p-3 text-left transition-colors",
                  active
                    ? "border-primary bg-primary/5"
                    : "border-input hover:border-foreground/30",
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">
                    {t(PRESET_LABEL_KEY[name])}
                  </span>
                  <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
                    {formatMultiplier(mult)}
                  </span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t(PRESET_DESCRIPTION_KEY[name])}
                </p>
                {preset && (
                  <p className="mt-2 text-[11px] text-muted-foreground">
                    {t("aiPresetParams", {
                      temperature: preset.temperature,
                      maxRetries: preset.max_retries,
                    })}
                  </p>
                )}
                {preset && (
                  <p className="mt-1 text-[11px] text-muted-foreground/80">
                    {preset.models[providerFilter as LLMProvider]}
                  </p>
                )}
              </button>
            );
          })}
          {form.effort_level === "custom" && (
            <div
              data-testid="settings-ai-preset-custom"
              data-active="true"
              className="col-span-full rounded-md border border-primary bg-primary/5 p-3"
            >
              <div className="text-sm font-medium">{t("aiPresetCustom")}</div>
              <p className="mt-1 text-xs text-muted-foreground">
                {t("aiPresetCustomHint")}
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Custom overrides */}
      <Card>
        <CardHeader>
          <CardTitle>{t("aiCustomOverrides")}</CardTitle>
          <CardDescription>
            {t.rich("aiCustomOverridesDescription", {
              b: (chunks) => <span className="font-medium">{chunks}</span>,
            })}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>{t("aiProvider")}</Label>
              <Select
                value={providerFilter}
                onValueChange={(v) => setProviderFilter(v)}
              >
                <SelectTrigger
                  data-testid="settings-ai-select-provider"
                  className="w-full"
                >
                  <SelectValue>
                    {providerOptions.find((p) => p.provider === providerFilter)
                      ?.label ?? providerFilter}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {providerOptions.map((p) => (
                    <SelectItem key={p.provider} value={p.provider}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                {t("aiProviderHint")}
              </p>
            </div>

            <div className="space-y-2">
              <Label>{t("aiModel")}</Label>
              <Select
                value={form.llm_model ?? USE_PRESET_DEFAULT}
                onValueChange={(v) =>
                  setCustomField(
                    "llm_model",
                    v === USE_PRESET_DEFAULT ? null : v,
                  )
                }
              >
                <SelectTrigger
                  data-testid="settings-ai-select-model"
                  className="w-full"
                >
                  <SelectValue>
                    {(() => {
                      const selected = form.llm_model ?? USE_PRESET_DEFAULT;
                      if (selected === USE_PRESET_DEFAULT)
                        return t("aiUsePresetDefault");
                      const match = modelsForProvider.find((m) => m.model === selected);
                      return match
                        ? `${match.label} (${formatMultiplier(match.credit_multiplier)})`
                        : selected;
                    })()}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={USE_PRESET_DEFAULT}>
                    {t("aiUsePresetDefault")}
                  </SelectItem>
                  {modelsForProvider.map((m) => (
                    <SelectItem key={m.model} value={m.model}>
                      {m.label} ({formatMultiplier(m.credit_multiplier)})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                {t.rich("aiEffectiveModel", {
                  mono: (chunks) => (
                    <span className="font-mono">{chunks}</span>
                  ),
                  provider: settings.effective_provider,
                  model: settings.effective_model,
                  multiplier: formatMultiplier(
                    settings.effective_credit_multiplier,
                  ),
                })}
              </p>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="settings-ai-input-temperature">
                {t("aiTemperature")}
              </Label>
              <span className="text-sm font-mono text-muted-foreground">
                {form.temperature.toFixed(2)}
              </span>
            </div>
            <input
              id="settings-ai-input-temperature"
              data-testid="settings-ai-input-temperature"
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={form.temperature}
              onChange={(e) =>
                setCustomField("temperature", Number(e.target.value))
              }
              className="w-full accent-primary"
            />
            <p className="text-xs text-muted-foreground">
              {t("aiTemperatureHint", {
                value: settings.effective_temperature,
              })}
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="settings-ai-input-retries">
              {t("aiMaxRetries")}
            </Label>
            <Input
              id="settings-ai-input-retries"
              data-testid="settings-ai-input-retries"
              type="number"
              min={1}
              max={10}
              step={1}
              value={form.max_retries}
              onChange={(e) =>
                setCustomField("max_retries", Number(e.target.value))
              }
            />
            <p className="text-xs text-muted-foreground">
              {t("aiRetriesHint", { value: settings.effective_max_retries })}
            </p>
          </div>

          <div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={handleReset}
              disabled={resetting || saving}
              data-testid="settings-ai-btn-reset"
            >
              {resetting ? t("aiResetting") : t("aiResetToBalanced")}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Content language */}
      <Card>
        <CardHeader>
          <CardTitle>{t("aiContentLanguage")}</CardTitle>
          <CardDescription>
            {t("aiContentLanguageDescription")}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <Select
            value={form.content_language}
            onValueChange={(v) =>
              setForm({ ...form, content_language: v as ContentLanguage })
            }
          >
            <SelectTrigger
              data-testid="settings-ai-select-language"
              className="w-full sm:w-64"
            >
              <SelectValue>{localeLabel(form.content_language)}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {CONTENT_LANGUAGES.map((lang) => (
                <SelectItem key={lang} value={lang}>
                  {localeLabel(lang)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            {t("aiContentLanguageHint")}
          </p>
        </CardContent>
      </Card>

      {/* Company context */}
      <Card>
        <CardHeader>
          <CardTitle>{t("aiCompanyContext")}</CardTitle>
          <CardDescription>
            {t("aiCompanyContextDescription")}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <Textarea
            data-testid="settings-ai-textarea-company-context"
            rows={6}
            maxLength={2000}
            value={form.company_context}
            onChange={(e) =>
              setForm({ ...form, company_context: e.target.value })
            }
            placeholder={t("aiCompanyContextPlaceholder")}
          />
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>{t("aiCompanyContextHint")}</span>
            <span data-testid="settings-ai-company-context-counter">
              {form.company_context.length} / 2000
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Sticky save bar */}
      {diff && (
        <div
          data-testid="settings-ai-save-bar"
          className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-background/95 backdrop-blur"
        >
          <div className="mx-auto flex max-w-3xl flex-col gap-2 px-6 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="text-sm text-muted-foreground">
              <p>{t("aiUnsavedChanges")}</p>
              {showSpendPreview && (
                <p
                  className="text-xs"
                  data-testid="settings-ai-spend-preview"
                >
                  {t.rich("aiSpendPreview", {
                    b: (chunks) => (
                      <span className="font-medium text-foreground">
                        {chunks}
                      </span>
                    ),
                    current: currentSpend,
                    preview: previewSpend,
                  })}
                </p>
              )}
            </div>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleDiscard}
                disabled={saving}
                data-testid="settings-ai-btn-discard"
              >
                {t("aiDiscard")}
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={handleSave}
                disabled={saving || !formValid}
                data-testid="settings-ai-btn-save"
              >
                {saving ? t("saving") : t("saveChanges")}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
