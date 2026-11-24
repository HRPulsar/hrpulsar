import type {
  AISettings,
  AISettingsPatch,
  AllowedModel,
  EffortLevel,
  PresetTier,
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

/** Form after a preset card is picked. A preset runs its own model, so the
 * custom pick is dropped — kept, it stayed stored and read as the
 * workspace's model (HRP-1240). */
export function withPreset(
  form: AISettingsFormState,
  name: EffortLevel,
): AISettingsFormState {
  return {
    ...form,
    effort_level: name,
    ...(name !== "custom" ? { llm_model: null } : {}),
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

/** HRP-1005: providers the picker shows — usable ones, and blocked ones
 * (visible but not selectable, so the admin sees why they are missing). */
export function selectableProviders(
  providers: ProviderStatus[],
): ProviderStatus[] {
  return providers.filter((p) => p.configured || p.blocked);
}

/** HRP-1005: the pinned model is not the one really used — the processor
 * list or the catalog replaced it. */
export function modelSubstituted(s: AISettings): boolean {
  return s.llm_model !== null && s.effective_model !== s.llm_model;
}

/** The tier whose model runs when nothing is picked: the custom tier
 * without a pick runs balanced, as the backend does. */
function runTier(form: AISettingsFormState): PresetTier {
  return form.effort_level === "custom" ? "balanced" : form.effort_level;
}

/** The form still holds the saved tier and model — the server's resolved
 * answers (effective model, its temperature) are exact for it. */
function matchesSaved(form: AISettingsFormState, settings: AISettings): boolean {
  return (
    form.effort_level === settings.effort_level &&
    (form.llm_model ?? null) === (settings.llm_model ?? null)
  );
}

/** Credit multiplier of the run the form would make: on the saved tier and
 * model the server's billed value (a pinned dated snapshot is missing from
 * the family-deduped /models list), else the /models entry of the run model,
 * 1.0 for a model the list does not price. */
export function formMultiplier(
  form: AISettingsFormState,
  settings: AISettings,
  models: AllowedModel[],
): number {
  if (matchesSaved(form, settings)) return settings.effective_credit_multiplier;
  const run = formRunModel(form, settings);
  return models.find((m) => m.model === run)?.credit_multiplier ?? 1.0;
}

/** The model a run would use with the form as it stands: on the saved tier
 * and model, the server's effective model (catalog and processor fallbacks
 * included); else the stored pick (it wins on any tier, as on the backend —
 * picking a preset clears it), else what the tier runs for this workspace
 * (HRP-1241: `preset_runs`, not the provider filter). */
export function formRunModel(
  form: AISettingsFormState,
  settings: AISettings,
): string | null {
  if (matchesSaved(form, settings)) return settings.effective_model;
  return form.llm_model || settings.preset_runs[runTier(form)]?.model || null;
}

/** HRP-1241: whether a model takes `temperature`, per the /models list. A
 * model the list does not know is assumed to take it. */
export function modelTakesTemperature(
  models: AllowedModel[],
  model: string | null | undefined,
): boolean {
  return models.find((m) => m.model === model)?.accepts_temperature ?? true;
}

/** HRP-1241: whether the slider's temperature reaches the model the form
 * would run. On the saved tier and model the server's answer is exact (its
 * dispatch target, catalog fallback included); a tier picked in the form
 * takes what that tier runs for the workspace; only a model just picked
 * falls back to the /models list. */
export function formTemperatureApplies(
  form: AISettingsFormState,
  settings: AISettings,
  models: AllowedModel[],
): boolean {
  if (matchesSaved(form, settings)) return settings.effective_temperature_applies;
  if (form.llm_model) return modelTakesTemperature(models, form.llm_model);
  return settings.preset_runs[runTier(form)]?.accepts_temperature ?? true;
}

/** HRP-1241: whether a preset card's temperature line applies. The card
 * shows the filtered provider's model and follows it; with no model to show
 * (a local-server filter) it says what the tier really runs. */
export function presetCardTakesTemperature(
  models: AllowedModel[],
  settings: AISettings,
  tier: PresetTier,
  shownModel: string | undefined,
): boolean {
  return shownModel
    ? modelTakesTemperature(models, shownModel)
    : (settings.preset_runs[tier]?.accepts_temperature ?? true);
}
