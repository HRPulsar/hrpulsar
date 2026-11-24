import { describe, expect, it } from "vitest";

import {
  brokenKeyProviders,
  buildPatchDiff,
  formMultiplier,
  formRunModel,
  formTemperatureApplies,
  isFormValid,
  modelSubstituted,
  modelTakesTemperature,
  presetCardTakesTemperature,
  roundUpTenth,
  selectableProviders,
  settingsToForm,
  withPreset,
  type AISettingsFormState,
} from "@/lib/ai-settings-form";
import type {
  AISettings,
  AllowedModel,
  ProviderStatus,
} from "@/lib/api/ai-settings";

const baseSettings: AISettings = {
  id: "00000000-0000-0000-0000-000000000001",
  tenant_id: "00000000-0000-0000-0000-000000000002",
  content_language: "en",
  effort_level: "balanced",
  llm_model: null,
  temperature: 0.3,
  max_retries: 5,
  company_context: null,
  effective_model: "claude-sonnet-5",
  effective_provider: "anthropic",
  effective_temperature: 0.3,
  effective_temperature_applies: false,
  effective_max_retries: 5,
  effective_credit_multiplier: 1.0,
  preset_runs: {
    fast: { model: "claude-haiku-5-5", accepts_temperature: false },
    balanced: { model: "claude-sonnet-5", accepts_temperature: false },
    thorough: { model: "claude-opus-5-5", accepts_temperature: false },
  },
  created_at: "2026-04-01T00:00:00Z",
  updated_at: "2026-04-01T00:00:00Z",
};

const baseForm: AISettingsFormState = settingsToForm(baseSettings);

describe("buildPatchDiff", () => {
  it("returns empty patch when nothing changed", () => {
    expect(buildPatchDiff(baseForm, baseForm)).toEqual({});
  });

  it("emits only effort_level when switching presets without touching custom fields", () => {
    const next = { ...baseForm, effort_level: "thorough" as const };
    expect(buildPatchDiff(baseForm, next)).toEqual({ effort_level: "thorough" });
  });

  it("emits temperature and effort_level=custom when temperature is edited", () => {
    const next = {
      ...baseForm,
      effort_level: "custom" as const,
      temperature: 0.7,
    };
    expect(buildPatchDiff(baseForm, next)).toEqual({
      effort_level: "custom",
      temperature: 0.7,
    });
  });

  it("emits llm_model with effort_level=custom when a model is picked", () => {
    const next = {
      ...baseForm,
      effort_level: "custom" as const,
      llm_model: "claude-opus-4-8",
    };
    expect(buildPatchDiff(baseForm, next)).toEqual({
      effort_level: "custom",
      llm_model: "claude-opus-4-8",
    });
  });

  it("emits llm_model: null when the user picks 'Use preset default'", () => {
    const baseWithModel: AISettingsFormState = {
      ...baseForm,
      effort_level: "custom",
      llm_model: "claude-opus-4-8",
    };
    const next = { ...baseWithModel, llm_model: null };
    expect(buildPatchDiff(baseWithModel, next)).toEqual({ llm_model: null });
  });

  it("emits company_context: null for an empty/whitespace string", () => {
    const next = { ...baseForm, company_context: "   " };
    expect(buildPatchDiff(baseForm, next)).toEqual({ company_context: null });
  });
});

describe("withPreset", () => {
  // HRP-1240: a preset runs its own model — the custom pick must not stay
  // stored and keep the workspace on it.
  const pinned: AISettingsFormState = {
    ...baseForm,
    effort_level: "custom",
    llm_model: "claude-opus-4-8",
  };

  it("drops the custom model when a preset is picked", () => {
    const next = withPreset(pinned, "balanced");
    expect(next).toEqual({ ...pinned, effort_level: "balanced", llm_model: null });
    expect(buildPatchDiff(pinned, next)).toEqual({
      effort_level: "balanced",
      llm_model: null,
    });
  });

  it("keeps the model when custom is picked", () => {
    expect(withPreset(pinned, "custom")).toEqual(pinned);
  });
});

describe("isFormValid", () => {
  it("accepts the default form", () => {
    expect(isFormValid(baseForm)).toBe(true);
  });

  it("rejects temperature out of [0, 1]", () => {
    expect(isFormValid({ ...baseForm, temperature: -0.1 })).toBe(false);
    expect(isFormValid({ ...baseForm, temperature: 1.5 })).toBe(false);
  });

  it("rejects non-integer max_retries", () => {
    expect(isFormValid({ ...baseForm, max_retries: 4.5 })).toBe(false);
  });

  it("rejects max_retries out of [1, 10]", () => {
    expect(isFormValid({ ...baseForm, max_retries: 0 })).toBe(false);
    expect(isFormValid({ ...baseForm, max_retries: 11 })).toBe(false);
  });

  it("rejects company_context > 2000 chars", () => {
    expect(
      isFormValid({ ...baseForm, company_context: "a".repeat(2001) }),
    ).toBe(false);
  });
});

describe("roundUpTenth", () => {
  it("matches the backend's round_credits_up", () => {
    expect(roundUpTenth(0)).toBe(0);
    expect(roundUpTenth(0.2)).toBe(0.2);
    expect(roundUpTenth(0.21)).toBe(0.3);
    expect(roundUpTenth(30)).toBe(30);
    expect(roundUpTenth(30.01)).toBe(30.1);
    expect(roundUpTenth(75)).toBe(75);
  });
});

describe("brokenKeyProviders (HRP-543)", () => {
  const provider = (
    over: Partial<ProviderStatus> & { provider: string },
  ): ProviderStatus => ({
    label: over.provider,
    configured: true,
    source: "byok",
    supports_local: false,
    key_status: null,
    blocked: false,
    ...over,
  });

  it("selects providers whose stored key no longer decrypts", () => {
    const rows = [
      provider({ provider: "anthropic", key_status: "ok" }),
      provider({ provider: "openai", key_status: "decrypt_failed" }),
      provider({ provider: "gemini", key_status: null }),
    ];
    expect(brokenKeyProviders(rows).map((p) => p.provider)).toEqual(["openai"]);
  });

  it("keeps a broken provider that is no longer configured", () => {
    // No platform key to fall back on: the page used to filter this row
    // out entirely, so the operator never learned why generation broke.
    const rows = [
      provider({
        provider: "openai",
        configured: false,
        source: null,
        key_status: "decrypt_failed",
      }),
    ];
    expect(brokenKeyProviders(rows)).toHaveLength(1);
  });

  it("returns nothing when every key is healthy", () => {
    expect(
      brokenKeyProviders([provider({ provider: "anthropic", key_status: "ok" })]),
    ).toEqual([]);
  });
});

describe("processor list in the settings form (HRP-1005)", () => {
  const status = (p: Partial<ProviderStatus>): ProviderStatus => ({
    provider: "openai",
    label: "OpenAI",
    configured: false,
    source: null,
    supports_local: false,
    key_status: null,
    blocked: false,
    ...p,
  });

  it("keeps configured and blocked providers, drops the rest", () => {
    const kept = selectableProviders([
      status({ provider: "anthropic", configured: true, source: "global" }),
      status({ provider: "openai", blocked: true }),
      status({ provider: "gemini" }),
    ]);
    expect(kept.map((p) => p.provider)).toEqual(["anthropic", "openai"]);
  });

  it("flags a pinned model that is not the one really used", () => {
    expect(
      modelSubstituted({ ...baseSettings, llm_model: "gpt-4o", effective_model: "claude-x" }),
    ).toBe(true);
    expect(
      modelSubstituted({ ...baseSettings, llm_model: "gpt-4o", effective_model: "gpt-4o" }),
    ).toBe(false);
    expect(modelSubstituted({ ...baseSettings, llm_model: null })).toBe(false);
  });
});

describe("temperature control (HRP-1241)", () => {
  const model = (id: string, accepts: boolean): AllowedModel => ({
    provider: "anthropic",
    model: id,
    label: id,
    credit_multiplier: 1,
    accepts_temperature: accepts,
  });
  const models = [
    model("claude-sonnet-5-5", false),
    model("claude-haiku-4-5-20251001", true),
  ];
  // The workspace runs fast on a local model behind its gateway; the
  // provider filter on the page plays no part.
  const settings: AISettings = {
    ...baseSettings,
    preset_runs: {
      ...baseSettings.preset_runs,
      fast: { model: "llama3.1", accepts_temperature: true },
    },
  };
  const pinned = {
    ...baseForm,
    effort_level: "custom" as const,
    llm_model: "claude-haiku-4-5-20251001",
  };

  it("runs the pick, else what the tier runs for the workspace", () => {
    expect(formRunModel(pinned, settings)).toBe("claude-haiku-4-5-20251001");
    expect(formRunModel({ ...baseForm, effort_level: "fast" }, settings)).toBe(
      "llama3.1",
    );
    // A stored pick wins on any tier, as on the backend (picking a preset
    // clears it — withPreset).
    expect(formRunModel({ ...pinned, effort_level: "fast" }, settings)).toBe(
      "claude-haiku-4-5-20251001",
    );
    // The custom tier without a pick runs balanced.
    expect(formRunModel({ ...pinned, llm_model: null }, settings)).toBe(
      "claude-sonnet-5",
    );
    expect(
      formRunModel(
        { ...baseForm, effort_level: "thorough" },
        { ...settings, preset_runs: {} },
      ),
    ).toBeNull();
  });

  it("runs the server's effective model while the form shows the saved state", () => {
    // A pin the platform admin disabled: the server already falls back.
    const saved = {
      ...settings,
      effort_level: "custom" as const,
      llm_model: "gpt-4o",
      effective_model: "gpt-6.2-sol",
    };
    expect(formRunModel(settingsToForm(saved), saved)).toBe("gpt-6.2-sol");
  });

  it("prices the saved run at the server's multiplier, a new pick off the list", () => {
    // A pinned dated snapshot is missing from the family-deduped list.
    const priced: AllowedModel[] = [
      { ...model("claude-opus-5-5", false), credit_multiplier: 1.4 },
    ];
    const saved = {
      ...settings,
      effort_level: "custom" as const,
      llm_model: "claude-opus-5-5-20261101",
      effective_model: "claude-opus-5-5-20261101",
      effective_credit_multiplier: 1.4,
    };
    expect(formMultiplier(settingsToForm(saved), saved, priced)).toBe(1.4);
    const picked = { ...settingsToForm(saved), llm_model: "claude-opus-5-5" };
    expect(formMultiplier(picked, saved, priced)).toBe(1.4);
    expect(
      formMultiplier({ ...picked, llm_model: "qwen2.5-72b" }, saved, priced),
    ).toBe(1.0);
  });

  it("a preset card follows the model it shows, else what its tier runs", () => {
    expect(
      presetCardTakesTemperature(models, settings, "balanced", "claude-sonnet-5-5"),
    ).toBe(false);
    // A local-server filter shows no model on the card.
    expect(presetCardTakesTemperature(models, settings, "fast", undefined)).toBe(true);
    expect(
      presetCardTakesTemperature(
        models,
        {
          ...settings,
          preset_runs: {
            balanced: { model: "claude-sonnet-5-5", accepts_temperature: false },
          },
        },
        "balanced",
        undefined,
      ),
    ).toBe(false);
  });

  it("reads whether a model takes temperature off the model list", () => {
    expect(modelTakesTemperature(models, "claude-sonnet-5-5")).toBe(false);
    expect(modelTakesTemperature(models, "claude-haiku-4-5-20251001")).toBe(true);
    // A model the list does not know is assumed to take it.
    expect(modelTakesTemperature(models, "qwen2.5-72b")).toBe(true);
    expect(modelTakesTemperature(models, null)).toBe(true);
  });

  it("takes the server's answer while the form shows the saved tier and model", () => {
    // The list says the pick takes temperature, the workspace's dispatch
    // target says it does not: the saved row's exact answer wins.
    const saved = {
      ...settings,
      effort_level: "custom" as const,
      llm_model: "claude-haiku-4-5-20251001",
      effective_temperature_applies: false,
    };
    expect(formTemperatureApplies(pinned, saved, models)).toBe(false);
    expect(
      formTemperatureApplies(
        settingsToForm(baseSettings),
        { ...baseSettings, effective_temperature_applies: true },
        models,
      ),
    ).toBe(true);
  });

  it("follows the tier's run for a tier picked in the form", () => {
    const fast = withPreset(settingsToForm(settings), "fast");
    expect(formTemperatureApplies(fast, settings, models)).toBe(true);
    const thorough = withPreset(settingsToForm(settings), "thorough");
    expect(formTemperatureApplies(thorough, settings, models)).toBe(false);
    // The custom tier without a pick runs balanced.
    const custom = { ...settingsToForm(settings), effort_level: "custom" as const };
    expect(formTemperatureApplies(custom, settings, models)).toBe(false);
  });

  it("asks the model list only for a model just picked", () => {
    expect(formTemperatureApplies(pinned, settings, models)).toBe(true);
    expect(
      formTemperatureApplies(
        { ...pinned, llm_model: "claude-sonnet-5-5" },
        settings,
        models,
      ),
    ).toBe(false);
    expect(
      formTemperatureApplies({ ...pinned, llm_model: "qwen2.5-72b" }, settings, models),
    ).toBe(true);
  });
});
