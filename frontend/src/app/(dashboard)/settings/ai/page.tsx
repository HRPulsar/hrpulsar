"use client";

import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { useIsSaas } from "@/hooks/use-is-saas";
import { usePermissions } from "@/hooks/use-permissions";
import { api } from "@/lib/api";
import {
  aiSettingsApi,
  type AISettings,
  type AllowedModel,
  type EffortLevel,
  type EffortPreset,
  type LLMProvider,
} from "@/lib/api/ai-settings";
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

const PRESET_LABEL: Record<Exclude<EffortLevel, "custom">, string> = {
  fast: "Fast",
  balanced: "Balanced",
  thorough: "Thorough",
};

function NotAvailable({ message }: { message: string }) {
  return (
    <div className="mx-auto max-w-3xl py-12 text-center">
      <h1 className="text-2xl font-semibold tracking-tight">AI Settings</h1>
      <p className="mt-3 text-sm text-muted-foreground">{message}</p>
    </div>
  );
}

function formatMultiplier(value: number): string {
  return `×${value % 1 === 0 ? value.toFixed(1) : value.toString()}`;
}

export default function AISettingsPage() {
  const { isAdmin } = usePermissions();
  const isSaas = useIsSaas();
  const [settings, setSettings] = useState<AISettings | null>(null);
  const [presets, setPresets] = useState<EffortPreset[]>([]);
  const [models, setModels] = useState<AllowedModel[]>([]);
  const [costMap, setCostMap] = useState<Record<string, number>>({});
  const [form, setForm] = useState<FormState | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [providerFilter, setProviderFilter] = useState<LLMProvider>("anthropic");

  useEffect(() => {
    if (!isAdmin) {
      setLoading(false);
      return;
    }
    Promise.all([
      aiSettingsApi.get(),
      aiSettingsApi.presets(),
      aiSettingsApi.models(),
      isSaas ? api.get<unknown>("/billing/costs").catch(() => null) : null,
    ])
      .then(([s, p, m, costs]) => {
        setSettings(s);
        setPresets(p);
        setModels(m);
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
          err instanceof Error ? err.message : "Failed to load AI settings",
        );
      })
      .finally(() => setLoading(false));
  }, [isAdmin, isSaas]);

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
    const presetModel = preset?.models[providerFilter];
    if (!presetModel) return 1.0;
    const entry = models.find((m) => m.model === presetModel);
    return entry?.credit_multiplier ?? 1.0;
  }, [form, models, presets, providerFilter]);

  if (!isAdmin) {
    return (
      <NotAvailable message="AI settings are visible to workspace administrators only." />
    );
  }
  if (loading || !settings || !form) {
    return (
      <div className="mx-auto max-w-3xl py-12 text-center text-sm text-muted-foreground">
        Loading AI settings...
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
      toast.success("Settings saved");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to save AI settings",
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
      toast.success("Settings reset to balanced preset");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to reset AI settings",
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
    const presetModel = preset.models[providerFilter];
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
        <h1 className="text-2xl font-semibold tracking-tight">AI Settings</h1>
        <p className="text-sm text-muted-foreground">
          These settings affect every AI operation in your workspace —
          competence generation, indicators, position drafts, and PDP
          suggestions.
        </p>
      </div>

      {/* Effort tier */}
      <Card>
        <CardHeader>
          <CardTitle>Effort tier</CardTitle>
          <CardDescription>
            Pick a preset that balances speed, cost, and quality. Each tier
            picks a different model — the multiplier shows how many credits
            an AI call costs versus the Balanced baseline.
          </CardDescription>
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
                    {PRESET_LABEL[name]}
                  </span>
                  <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
                    {formatMultiplier(mult)}
                  </span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {preset?.description ?? ""}
                </p>
                {preset && (
                  <p className="mt-2 text-[11px] text-muted-foreground">
                    temperature {preset.temperature} · max_retries{" "}
                    {preset.max_retries}
                  </p>
                )}
                {preset && (
                  <p className="mt-1 text-[11px] text-muted-foreground/80">
                    {preset.models[providerFilter]}
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
              <div className="text-sm font-medium">Custom</div>
              <p className="mt-1 text-xs text-muted-foreground">
                Effective values come from the fields below. Switch back to a
                preset to discard custom values.
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Custom overrides */}
      <Card>
        <CardHeader>
          <CardTitle>Custom overrides</CardTitle>
          <CardDescription>
            Editing any field below switches the effort tier to{" "}
            <span className="font-medium">Custom</span>. Pick a model from the
            whitelist or fall back to the active preset&apos;s default.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>Provider</Label>
              <Select
                value={providerFilter}
                onValueChange={(v) => setProviderFilter(v as LLMProvider)}
              >
                <SelectTrigger
                  data-testid="settings-ai-select-provider"
                  className="w-full"
                >
                  <SelectValue>
                    {providerFilter === "anthropic"
                      ? "Anthropic"
                      : providerFilter === "openai"
                        ? "OpenAI"
                        : providerFilter === "gemini"
                          ? "Google"
                          : ""}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="anthropic">Anthropic</SelectItem>
                  <SelectItem value="openai">OpenAI</SelectItem>
                  <SelectItem value="gemini">Google</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                Filters the model list below.
              </p>
            </div>

            <div className="space-y-2">
              <Label>Model</Label>
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
                      if (selected === USE_PRESET_DEFAULT) return "Use preset default";
                      const match = modelsForProvider.find((m) => m.model === selected);
                      return match
                        ? `${match.label} (${formatMultiplier(match.credit_multiplier)})`
                        : selected;
                    })()}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={USE_PRESET_DEFAULT}>
                    Use preset default
                  </SelectItem>
                  {modelsForProvider.map((m) => (
                    <SelectItem key={m.model} value={m.model}>
                      {m.label} ({formatMultiplier(m.credit_multiplier)})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                Effective:{" "}
                <span className="font-mono">{settings.effective_provider}</span>{" "}
                ·{" "}
                <span className="font-mono">{settings.effective_model}</span> ·{" "}
                {formatMultiplier(settings.effective_credit_multiplier)}
              </p>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="settings-ai-input-temperature">Temperature</Label>
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
              Lower values are more deterministic; higher values produce more
              diverse output. Effective: {settings.effective_temperature}.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="settings-ai-input-retries">Max retries</Label>
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
              JSON parse retries per AI call. Effective:{" "}
              {settings.effective_max_retries}.
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
              {resetting ? "Resetting..." : "Reset to balanced preset"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Content language */}
      <Card>
        <CardHeader>
          <CardTitle>Content language</CardTitle>
          <CardDescription>
            Language used by the model when generating competences,
            indicators, positions, and PDP goals.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <Select
            value={form.content_language}
            onValueChange={(v) =>
              setForm({ ...form, content_language: v as "en" })
            }
          >
            <SelectTrigger
              data-testid="settings-ai-select-language"
              className="w-full sm:w-64"
            >
              <SelectValue>
                {form.content_language === "en" ? "English" : form.content_language}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="en">English</SelectItem>
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            More languages will be added in the i18n phase.
          </p>
        </CardContent>
      </Card>

      {/* Company context */}
      <Card>
        <CardHeader>
          <CardTitle>Company context</CardTitle>
          <CardDescription>
            Appended to every AI prompt as additional context. Describe your
            company so the model picks competences and positions relevant to
            your business.
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
            placeholder="Acme Corp builds payment infrastructure for B2B SaaS..."
          />
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>Markdown is not interpreted; plain text only.</span>
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
              <p>You have unsaved changes.</p>
              {showSpendPreview && (
                <p
                  className="text-xs"
                  data-testid="settings-ai-spend-preview"
                >
                  Competence generation now: {currentSpend} →{" "}
                  <span className="font-medium text-foreground">
                    {previewSpend}
                  </span>{" "}
                  credits per call.
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
                Discard
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={handleSave}
                disabled={saving || !formValid}
                data-testid="settings-ai-btn-save"
              >
                {saving ? "Saving..." : "Save changes"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
