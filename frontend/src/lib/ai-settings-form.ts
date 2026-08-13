import type {
  AISettings,
  AISettingsPatch,
  EffortLevel,
  ProviderStatus,
} from "@/lib/api/ai-settings";

export type AISettingsFormState = {
  content_language: AISettings["content_language"];
  effort_level: EffortLevel;
  llm_model: string | null;
  temperature: number;
  max_retries: number;
  company_context: string;
};

export function settingsToForm(s: AISettings): AISettingsFormState {
  return {
    content_language: s.content_language,
    effort_level: s.effort_level,
    llm_model: s.llm_model,
    temperature: s.temperature,
    max_retries: s.max_retries,
    company_context: s.company_context ?? "",
  };
}

export function buildPatchDiff(
  base: AISettingsFormState,
  next: AISettingsFormState,
): AISettingsPatch {
  const patch: AISettingsPatch = {};
  if (base.content_language !== next.content_language) {
    patch.content_language = next.content_language;
  }
  if (base.effort_level !== next.effort_level) {
    patch.effort_level = next.effort_level;
  }
  if ((base.llm_model ?? null) !== (next.llm_model ?? null)) {
    patch.llm_model = next.llm_model;
  }
  if (base.temperature !== next.temperature) {
    patch.temperature = next.temperature;
  }
  if (base.max_retries !== next.max_retries) {
    patch.max_retries = next.max_retries;
  }
  if ((base.company_context || "") !== (next.company_context || "")) {
    patch.company_context =
      next.company_context.trim() === "" ? null : next.company_context;
  }
  return patch;
}

export function isFormValid(form: AISettingsFormState): boolean {
  if (form.temperature < 0 || form.temperature > 1) return false;
  if (
    !Number.isInteger(form.max_retries) ||
    form.max_retries < 1 ||
    form.max_retries > 10
  )
    return false;
  if (form.company_context.length > 2000) return false;
  return true;
}

export function roundUpTenth(value: number): number {
  return Math.ceil(value * 10) / 10;
}

/**
 * Providers whose stored BYOK key no longer decrypts (HRP-543).
 *
 * The backend has reported `key_status` since HRP-514, but nothing read
 * it: a provider whose key became unreadable (an `ENCRYPTION_KEY` rotated
 * without re-encrypting, say) silently fell back to the platform key — or,
 * with no platform key, went `configured: false` and disappeared from the
 * page altogether. Selecting on the status instead of on `configured`
 * keeps the broken provider visible so the operator can re-issue the key.
 */
export function brokenKeyProviders(
  providers: ProviderStatus[],
): ProviderStatus[] {
  return providers.filter((p) => p.key_status === "decrypt_failed");
}
