import { describe, expect, it } from "vitest";

import {
  brokenKeyProviders,
  buildPatchDiff,
  isFormValid,
  roundUpTenth,
  settingsToForm,
  type AISettingsFormState,
} from "@/lib/ai-settings-form";
import type { AISettings, ProviderStatus } from "@/lib/api/ai-settings";

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
  effective_max_retries: 5,
  effective_credit_multiplier: 1.0,
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
