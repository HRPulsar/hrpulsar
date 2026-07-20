"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Loader2, KeyRound, Plus, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { RecruitmentBreadcrumbs } from "@/components/recruitment";
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

const PROVIDERS = [
  { value: "anthropic", label: "Anthropic Claude" },
  { value: "openai", label: "OpenAI" },
  { value: "gemini", label: "Google Gemini" },
  { value: "azure", label: "Azure OpenAI" },
  { value: "yandex", label: "Yandex GPT" },
  { value: "gigachat", label: "GigaChat" },
];

export default function LLMProvidersPage() {
  const [rows, setRows] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [draft, setDraft] = useState({
    provider: "anthropic",
    model: "claude-sonnet-4-6",
    api_key: "",
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
      toast.error("Provide a model name");
      return;
    }
    setCreating(true);
    try {
      await api.post("/recruitment/settings/llm-providers", {
        provider: draft.provider,
        model: draft.model,
        api_key: draft.api_key || null,
        is_active: true,
      });
      toast.success("Provider added");
      setDraft({ provider: "anthropic", model: "claude-sonnet-4-6", api_key: "" });
      void load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error");
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
      toast.error(err instanceof Error ? err.message : "Error");
    } finally {
      setSavingId(null);
    }
  }

  async function handleDelete(p: Provider) {
    if (!confirm(`Delete ${p.provider}/${p.model}?`)) return;
    setSavingId(p.id);
    try {
      await api.delete(`/recruitment/settings/llm-providers/${p.id}`);
      void load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error");
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div className="space-y-5" data-testid="recruitment-llm-providers-page">
      <RecruitmentBreadcrumbs
        segments={[
          { label: "Settings", href: "/recruitment/settings" },
          { label: "LLM providers" },
        ]}
      />
      <header>
        <h1 className="text-xl font-semibold tracking-tight">
          LLM providers (BYOK)
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Bring your own API key to generate vacancy profiles, questions and
          interview analysis. The key is stored encrypted (AES-GCM); only the
          last 4 characters are returned in API responses.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Add provider</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1">
              <Label htmlFor="llm-provider">Provider</Label>
              <select
                id="llm-provider"
                value={draft.provider}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, provider: e.target.value }))
                }
                className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
                data-testid="llm-input-provider"
              >
                {PROVIDERS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="llm-model">Model</Label>
              <Input
                id="llm-model"
                value={draft.model}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, model: e.target.value }))
                }
                placeholder="claude-sonnet-4-6"
                data-testid="llm-input-model"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="llm-key">API key</Label>
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
              Add
            </Button>
          </div>
        </CardContent>
      </Card>

      <section className="space-y-2">
        <h2 className="text-sm font-medium">Connected providers</h2>
        {loading ? (
          <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin" />
            Loading…
          </div>
        ) : rows.length === 0 ? (
          <div className="rounded-md border border-dashed p-6 text-center text-xs text-muted-foreground">
            No providers connected. Without BYOK, environment keys will be used.
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
                        Active
                      </Badge>
                    ) : (
                      <Badge variant="outline">Disabled</Badge>
                    )}
                  </div>
                  <span className="flex items-center gap-1 text-xs text-muted-foreground">
                    <KeyRound className="size-3" />
                    {p.api_key_masked || "key not set"}
                  </span>
                </div>
                <div className="flex items-center gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => handleToggle(p)}
                    disabled={savingId === p.id}
                    data-testid={`llm-btn-toggle-${p.id}`}
                  >
                    <Save className="size-3.5" />
                    {p.is_active ? "Disable" : "Enable"}
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
  );
}
