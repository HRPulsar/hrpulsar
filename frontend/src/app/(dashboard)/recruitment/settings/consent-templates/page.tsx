"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ConsentTemplate } from "@/lib/types";
import { BADGE_COLOR } from "@/lib/badge-tones";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Loader2, Plus, Save, Star } from "lucide-react";
import { toast } from "sonner";
import { RecruitmentBreadcrumbs } from "@/components/recruitment";

const DEFAULT_BODY = `I consent to the processing of my personal data and audio recording of the interview as part of the hiring process.

Purpose of processing: assessment of fit for the position.
Retention period: 6 months from the date of signing.

By signing this consent, I confirm that I have read the data processing policy and may withdraw my consent by writing to hr@example.com.`;

export default function ConsentTemplatesPage() {
  const [templates, setTemplates] = useState<ConsentTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({
    name: "",
    body: DEFAULT_BODY,
    language: "en",
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api.get<ConsentTemplate[]>(
        "/recruitment/consent-templates",
      );
      setTemplates(rows);
    } catch {
      setTemplates([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreate() {
    if (!draft.name.trim() || !draft.body.trim()) {
      toast.error("Fill in the template name and body");
      return;
    }
    setCreating(true);
    try {
      await api.post<ConsentTemplate>("/recruitment/consent-templates", {
        name: draft.name,
        body: draft.body,
        language: draft.language,
        is_active: true,
      });
      toast.success("Template created and set as active");
      setDraft({ name: "", body: DEFAULT_BODY, language: "en" });
      void load();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to create template",
      );
    } finally {
      setCreating(false);
    }
  }

  async function handleUpdate(t: ConsentTemplate, patch: Partial<ConsentTemplate>) {
    setSavingId(t.id);
    try {
      await api.put<ConsentTemplate>(
        `/recruitment/consent-templates/${t.id}`,
        patch,
      );
      void load();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to update template",
      );
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div data-testid="recruitment-consent-templates" className="space-y-5">
      <RecruitmentBreadcrumbs
        segments={[
          { label: "Settings", href: "/recruitment/settings" },
          { label: "Consent templates" },
        ]}
      />
      <header>
        <h1 className="text-xl font-semibold tracking-tight">
          Consent templates
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          The active template is sent to a candidate when consent is requested.
          Only one template can be active at any given time.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Create a new template</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="tpl-name">Name</Label>
            <Input
              id="tpl-name"
              value={draft.name}
              onChange={(e) =>
                setDraft((d) => ({ ...d, name: e.target.value }))
              }
              placeholder='For example, "Consent 2026"'
              data-testid="consent-tpl-input-name"
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-[1fr_8rem]">
            <div className="space-y-1">
              <Label htmlFor="tpl-body">Consent text</Label>
              <Textarea
                id="tpl-body"
                rows={10}
                value={draft.body}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, body: e.target.value }))
                }
                data-testid="consent-tpl-input-body"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="tpl-lang">Language</Label>
              <select
                id="tpl-lang"
                value={draft.language}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, language: e.target.value }))
                }
                className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
              >
                <option value="en">English</option>
              </select>
            </div>
          </div>
          <div className="flex justify-end">
            <Button
              onClick={handleCreate}
              disabled={creating}
              data-testid="consent-tpl-btn-create"
            >
              {creating ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Plus className="size-4" />
              )}
              Create as active
            </Button>
          </div>
        </CardContent>
      </Card>

      <section className="space-y-2">
        <h2 className="text-sm font-medium">Existing templates</h2>
        {loading ? (
          <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin" />
            Loading…
          </div>
        ) : templates.length === 0 ? (
          <div className="rounded-md border border-dashed p-6 text-center text-xs text-muted-foreground">
            No templates yet. Create your first one above.
          </div>
        ) : (
          <ul className="space-y-2">
            {templates.map((t) => (
              // ``key`` includes name+body+version so the row remounts when
              // an external change lands (e.g., another admin edits) and
              // the row picks up the new values cleanly without an in-effect
              // setState dance that violates the lint rule.
              <TemplateRow
                key={`${t.id}::${t.version}::${t.is_active ? 1 : 0}`}
                template={t}
                saving={savingId === t.id}
                onUpdate={handleUpdate}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function TemplateRow({
  template,
  saving,
  onUpdate,
}: {
  template: ConsentTemplate;
  saving: boolean;
  onUpdate: (
    template: ConsentTemplate,
    patch: Partial<ConsentTemplate>,
  ) => Promise<void>;
}) {
  // The row is keyed on (id, version, is_active) by the parent — when the
  // server-side template changes, React remounts this row and these
  // useState calls re-seed from the fresh prop. That avoids a sync-in-effect
  // setState pattern that React's lint rule forbids.
  const [name, setName] = useState(template.name);
  const [body, setBody] = useState(template.body);

  const dirty = name !== template.name || body !== template.body;

  return (
    <li
      data-testid={`consent-tpl-row-${template.id}`}
      className="space-y-2 rounded-lg border p-3"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="h-7 max-w-xs"
          />
          {template.is_active ? (
            <Badge className={BADGE_COLOR.emerald}>Active</Badge>
          ) : (
            <Badge variant="outline">Inactive</Badge>
          )}
          <span className="text-[11px] text-muted-foreground">
            v{template.version}
          </span>
        </div>
        <div className="flex items-center gap-1">
          {!template.is_active && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onUpdate(template, { is_active: true })}
              disabled={saving}
              data-testid={`consent-tpl-btn-activate-${template.id}`}
            >
              <Star className="size-3.5" />
              Set as active
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => onUpdate(template, { name, body })}
            disabled={saving || !dirty}
            data-testid={`consent-tpl-btn-save-${template.id}`}
          >
            {saving ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Save className="size-3.5" />
            )}
            Save
          </Button>
        </div>
      </div>
      <Textarea
        rows={6}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        className="text-xs"
      />
    </li>
  );
}
