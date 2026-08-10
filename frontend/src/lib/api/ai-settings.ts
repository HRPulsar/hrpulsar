import { api } from "../api";
import { EE_CONTENT_LANGUAGES } from "../locale-ee";

export type ContentLanguage = "en" | "de" | "ru";
/** Languages the AI may generate content in. Adding one: widen the
 * ContentLanguage union here and the backend Literal in
 * ai_settings/schemas.py (no DB migration — HRP-480 dropped the CHECK).
 * Deliberately NOT tied to AVAILABLE_LOCALES: the content language is
 * orthogonal to the interface locale, so an en-only UI deployment may
 * still generate AI content in German. Enterprise-only languages (ru)
 * join the select options via locale-ee.ts — the union and the backend
 * Literal accept them in every edition, community just never offers
 * them in the UI. */
export const CONTENT_LANGUAGES: ContentLanguage[] = [
  "en",
  "de",
  ...(EE_CONTENT_LANGUAGES as readonly ContentLanguage[]),
];
export type EffortLevel = "fast" | "balanced" | "thorough" | "custom";
export type LLMProvider = "anthropic" | "openai" | "gemini";

export interface ProviderStatus {
  provider: string;
  label: string;
  configured: boolean;
  source: "global" | "byok" | "local" | null;
  supports_local: boolean;
  /** State of the tenant's stored key, when there is one (HRP-514).
   * `decrypt_failed` → the row exists but its key is unreadable, so
   * generation falls back to the platform key. */
  key_status: "ok" | "decrypt_failed" | null;
}

export interface AISettings {
  id: string;
  tenant_id: string;
  content_language: ContentLanguage;
  effort_level: EffortLevel;
  llm_model: string | null;
  temperature: number;
  max_retries: number;
  company_context: string | null;
  effective_model: string;
  // Not a closed set anymore: discovered/local providers (HRP-465).
  effective_provider: string;
  effective_temperature: number;
  effective_max_retries: number;
  effective_credit_multiplier: number;
  created_at: string;
  updated_at: string;
}

export interface AllowedModel {
  provider: string;
  model: string;
  label: string;
  credit_multiplier: number;
}

export interface EffortPreset {
  name: EffortLevel;
  description: string;
  temperature: number;
  max_retries: number;
  models: Record<LLMProvider, string>;
}

export type AISettingsPatch = Partial<{
  content_language: ContentLanguage;
  effort_level: EffortLevel;
  llm_model: string | null;
  temperature: number;
  max_retries: number;
  company_context: string | null;
}>;

const BASE = "/admin/ai-settings";

export const aiSettingsApi = {
  get: () => api.get<AISettings>(BASE),
  update: (patch: AISettingsPatch) => api.patch<AISettings>(BASE, patch),
  reset: () => api.post<AISettings>(`${BASE}/reset`),
  presets: () => api.get<EffortPreset[]>(`${BASE}/presets`),
  models: () => api.get<AllowedModel[]>(`${BASE}/models`),
  providers: () => api.get<ProviderStatus[]>(`${BASE}/providers`),
};
