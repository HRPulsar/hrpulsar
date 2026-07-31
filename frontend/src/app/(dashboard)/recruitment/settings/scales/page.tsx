"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Loader2, Plus, Star, Trash2, Archive, ArrowDown, ArrowUp } from "lucide-react";
import { toast } from "sonner";
import { RecruitmentBreadcrumbs } from "@/components/recruitment";
import { BADGE_COLOR } from "@/lib/badge-tones";

type ScaleLevel = {
  id?: string;
  value: number;
  label: string;
  description?: string | null;
  weight: number;
  color?: string | null;
  sort_order: number;
};

// HRP-476: the seeded level names are recruiter-facing copy that lands in
// the draft form (and, on save, in the tenant's scale), so they come from
// the `recruitment` i18n namespace. The static list owns everything else.
const EMPTY_LEVEL_SEEDS: Array<Omit<ScaleLevel, "label"> & { labelKey: string }> =
  [
    {
      value: 1,
      labelKey: "scaleLevelNotSuitable",
      weight: 0,
      sort_order: 0,
      color: "rose",
    },
    {
      value: 2,
      labelKey: "scaleLevelBelowExpectations",
      weight: 33,
      sort_order: 1,
      color: "amber",
    },
    {
      value: 3,
      labelKey: "scaleLevelMeetsExpectations",
      weight: 66,
      sort_order: 2,
      color: "blue",
    },
    {
      value: 4,
      labelKey: "scaleLevelExceedsExpectations",
      weight: 100,
      sort_order: 3,
      color: "emerald",
    },
  ];

function buildEmptyLevels(t: (key: string) => string): ScaleLevel[] {
  return EMPTY_LEVEL_SEEDS.map(({ labelKey, ...rest }) => ({
    ...rest,
    label: t(labelKey),
  }));
}

type Scale = {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  is_default: boolean;
  archived_at: string | null;
  divergence_threshold: number;
  version: number;
  created_at: string;
  updated_at: string;
  levels: ScaleLevel[];
};

export default function ScaleSettingsPage() {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [scales, setScales] = useState<Scale[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({
    name: "",
    description: "",
    is_default: false,
    divergence_threshold: 2,
    levels: buildEmptyLevels(t),
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api.get<Scale[]>("/v1/tenants/me/assessment-scales");
      setScales(rows);
    } catch {
      setScales([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function addLevel() {
    setDraft((d) => {
      const next = [...d.levels];
      const last = next[next.length - 1];
      next.push({
        value: (last?.value ?? 0) + 1,
        label: t("scaleLevelDefaultName", { index: String(next.length + 1) }),
        weight: Math.min(100, (last?.weight ?? 0) + 25),
        sort_order: next.length,
      });
      return { ...d, levels: next };
    });
  }

  function removeLevel(idx: number) {
    setDraft((d) => {
      const next = d.levels.filter((_, i) => i !== idx);
      return { ...d, levels: next.map((l, i) => ({ ...l, sort_order: i })) };
    });
  }

  function moveLevel(idx: number, direction: -1 | 1) {
    setDraft((d) => {
      const next = [...d.levels];
      const target = idx + direction;
      if (target < 0 || target >= next.length) return d;
      [next[idx], next[target]] = [next[target]!, next[idx]!];
      return {
        ...d,
        levels: next.map((l, i) => ({ ...l, sort_order: i })),
      };
    });
  }

  function updateLevel(idx: number, patch: Partial<ScaleLevel>) {
    setDraft((d) => {
      const next = [...d.levels];
      next[idx] = { ...next[idx]!, ...patch };
      return { ...d, levels: next };
    });
  }

  async function handleCreate() {
    if (!draft.name.trim()) {
      toast.error(t("scaleNameRequired"));
      return;
    }
    if (draft.levels.length < 2 || draft.levels.length > 10) {
      toast.error(t("scaleLevelsRange"));
      return;
    }
    const values = new Set(draft.levels.map((l) => l.value));
    if (values.size !== draft.levels.length) {
      toast.error(t("scaleLevelValuesUnique"));
      return;
    }
    setCreating(true);
    try {
      await api.post<Scale>("/v1/tenants/me/assessment-scales", {
        name: draft.name,
        description: draft.description || null,
        is_default: draft.is_default,
        divergence_threshold: draft.divergence_threshold,
        levels: draft.levels.map((lvl, i) => ({
          value: lvl.value,
          label: lvl.label,
          description: lvl.description ?? null,
          weight: lvl.weight,
          color: lvl.color ?? null,
          sort_order: i,
        })),
      });
      toast.success(t("scaleToastCreated"));
      setDraft({
        name: "",
        description: "",
        is_default: false,
        divergence_threshold: 2,
        levels: buildEmptyLevels(t),
      });
      void load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("scaleCreateFailed"));
    } finally {
      setCreating(false);
    }
  }

  async function handleArchive(scale: Scale) {
    setSavingId(scale.id);
    try {
      await api.post(`/v1/assessment-scales/${scale.id}/archive`);
      void load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("scaleArchiveFailed"));
    } finally {
      setSavingId(null);
    }
  }

  async function handleMakeDefault(scale: Scale) {
    setSavingId(scale.id);
    try {
      await api.patch(`/v1/assessment-scales/${scale.id}`, {
        is_default: true,
      });
      void load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("scaleUpdateFailed"));
    } finally {
      setSavingId(null);
    }
  }

  async function handleDelete(scale: Scale) {
    if (!confirm(t("scaleDeleteConfirm", { name: scale.name }))) return;
    setSavingId(scale.id);
    try {
      await api.delete(`/v1/assessment-scales/${scale.id}`);
      void load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("scaleDeleteFailed"));
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div className="space-y-5" data-testid="assessment-scale-page-list">
      <RecruitmentBreadcrumbs
        segments={[
          { label: tc("settings"), href: "/recruitment/settings" },
          { label: t("scalesTitle") },
        ]}
      />
      <header>
        <h1 className="text-xl font-semibold tracking-tight">
          {t("scalesTitle")}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("scalesDescription")}
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("scaleNewCardTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="scale-name">{t("fieldName")}</Label>
              <Input
                id="scale-name"
                value={draft.name}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, name: e.target.value }))
                }
                placeholder={t("scaleNamePlaceholder")}
                data-testid="assessment-scale-form-name"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="scale-description">
                {t("scaleDescriptionLabel")}
              </Label>
              <Input
                id="scale-description"
                value={draft.description}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, description: e.target.value }))
                }
              />
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="scale-divergence">
                {t("scaleDivergenceLabel")}
              </Label>
              <Input
                id="scale-divergence"
                type="number"
                min={1}
                max={10}
                value={draft.divergence_threshold}
                onChange={(e) =>
                  setDraft((d) => ({
                    ...d,
                    divergence_threshold: Number(e.target.value),
                  }))
                }
              />
              <p className="text-xs text-muted-foreground">
                {t("scaleDivergenceHint")}
              </p>
            </div>
            <div className="flex items-end gap-2">
              <Label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={draft.is_default}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, is_default: e.target.checked }))
                  }
                />
                {t("scaleMakeDefaultCheckbox")}
              </Label>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>{t("scaleLevelsLabel")}</Label>
              <Button
                size="sm"
                variant="outline"
                onClick={addLevel}
                disabled={draft.levels.length >= 10}
                data-testid="assessment-scale-form-add-level-btn"
              >
                <Plus className="size-3.5" /> {t("scaleAddLevel")}
              </Button>
            </div>
            <ul className="space-y-2">
              {draft.levels.map((lvl, idx) => (
                <li
                  key={idx}
                  className="grid items-center gap-2 rounded-md border p-2 md:grid-cols-[60px_1fr_1fr_90px_70px]"
                >
                  <Input
                    type="number"
                    min={0}
                    value={lvl.value}
                    onChange={(e) =>
                      updateLevel(idx, { value: Number(e.target.value) })
                    }
                    data-testid={`assessment-scale-form-level-${idx}-value`}
                  />
                  <Input
                    value={lvl.label}
                    onChange={(e) =>
                      updateLevel(idx, { label: e.target.value })
                    }
                    placeholder={t("scaleLevelLabelPlaceholder")}
                    data-testid={`assessment-scale-form-level-${idx}-label`}
                  />
                  <Input
                    value={lvl.description ?? ""}
                    onChange={(e) =>
                      updateLevel(idx, { description: e.target.value })
                    }
                    placeholder={t("scaleLevelDescriptionPlaceholder")}
                  />
                  <Input
                    type="number"
                    min={0}
                    max={100}
                    value={lvl.weight}
                    onChange={(e) =>
                      updateLevel(idx, { weight: Number(e.target.value) })
                    }
                  />
                  <div className="flex justify-end gap-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => moveLevel(idx, -1)}
                      disabled={idx === 0}
                    >
                      <ArrowUp className="size-3" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => moveLevel(idx, 1)}
                      disabled={idx === draft.levels.length - 1}
                    >
                      <ArrowDown className="size-3" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => removeLevel(idx)}
                      disabled={draft.levels.length <= 2}
                    >
                      <Trash2 className="size-3" />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          <div className="flex justify-end">
            <Button
              onClick={handleCreate}
              disabled={creating}
              data-testid="assessment-scale-page-create-btn"
            >
              {creating ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Plus className="size-4" />
              )}
              {t("scaleCreateButton")}
            </Button>
          </div>
        </CardContent>
      </Card>

      <section className="space-y-2">
        <h2 className="text-sm font-medium">{t("scaleExistingTitle")}</h2>
        {loading ? (
          <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin" />
            {t("loading")}
          </div>
        ) : scales.length === 0 ? (
          <div className="rounded-md border border-dashed p-6 text-center text-xs text-muted-foreground">
            {t("scaleEmpty")}
          </div>
        ) : (
          <ul className="space-y-2">
            {scales.map((s) => (
              <li
                key={s.id}
                className="space-y-2 rounded-lg border p-3"
                data-testid={`assessment-scale-row-${s.id}`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-col gap-0.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">{s.name}</span>
                      {s.is_default && (
                        <Badge className={BADGE_COLOR.emerald}>
                          {t("scaleBadgeDefault")}
                        </Badge>
                      )}
                      {s.archived_at && (
                        <Badge variant="outline">{t("statusArchived")}</Badge>
                      )}
                    </div>
                    {s.description && (
                      <span className="text-xs text-muted-foreground">
                        {s.description}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-1">
                    {!s.is_default && !s.archived_at && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleMakeDefault(s)}
                        disabled={savingId === s.id}
                      >
                        <Star className="size-3.5" /> {t("scaleMakeDefaultAction")}
                      </Button>
                    )}
                    {!s.archived_at && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleArchive(s)}
                        disabled={savingId === s.id}
                      >
                        <Archive className="size-3.5" /> {t("actionArchive")}
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleDelete(s)}
                      disabled={savingId === s.id}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                </div>
                <div className="grid gap-1 text-xs">
                  {s.levels.map((lvl) => (
                    <div
                      key={lvl.id ?? `${lvl.value}-${lvl.label}`}
                      className="flex items-center gap-2"
                    >
                      <span className="font-mono w-8">{lvl.value}</span>
                      <span className="font-medium">{lvl.label}</span>
                      <span className="text-muted-foreground">
                        {t("scaleWeight", { weight: String(lvl.weight) })}
                      </span>
                      {lvl.description && (
                        <span className="text-muted-foreground">
                          — {lvl.description}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
