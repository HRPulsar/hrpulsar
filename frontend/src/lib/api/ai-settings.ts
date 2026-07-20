import { api } from "../api";

export type ContentLanguage = "en";
export type EffortLevel = "fast" | "balanced" | "thorough" | "custom";
export type LLMProvider = "anthropic" | "openai" | "gemini";

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
  effective_provider: LLMProvider;
  effective_temperature: number;
  effective_max_retries: number;
  effective_credit_multiplier: number;
  created_at: string;
  updated_at: string;
}

export interface AllowedModel {
  provider: LLMProvider;
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
};
