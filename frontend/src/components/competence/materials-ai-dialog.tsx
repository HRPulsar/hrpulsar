"use client";

import { useEffect, useMemo, useState } from "react";
import { Link2, Loader2, Search, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";

import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { skillLevelLabel } from "@/lib/reference-labels";
import type { Material, SkillLevel } from "@/lib/types";

/**
 * HRP-51 review: rewritten so the AI gets the full per-competence context
 * the operator can opt into — indicators, specializations, divisions,
 * sibling competences and the company description — instead of just a
 * spec multiselect. UI follows the same Linked-aware pattern shipped for
 * `group` and `competence_indicators` scopes (HRP-114): full tenant list,
 * linked rows pre-checked with a link marker + tooltip, search and a
 * "show linked only" filter appear once the list passes 15 rows.
 */

export interface MaterialsAIDialogProps {
  competenceId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Skill levels available in the tenant (driven by the parent page). */
  skillLevels: SkillLevel[];
  /** Called after a successful bulk save so the parent can refetch. */
  onSaved: (createdIds: string[]) => void;
}

interface ContextGroup {
  id: string;
  title: string;
}

interface ContextCompetence {
  id: string;
  title: string;
  description: string | null;
  type: string | null;
  group: ContextGroup | null;
}

interface ContextIndicator {
  id: string;
  title: string;
  skill_level_id: string | null;
  skill_level_title: string | null;
}

interface ContextLinkedItem {
  id: string;
  title: string;
  is_linked: boolean;
}

interface ContextSibling {
  id: string;
  title: string;
}

interface MaterialsContextOptions {
  competence: ContextCompetence;
  indicators: ContextIndicator[];
  specializations: ContextLinkedItem[];
  divisions: ContextLinkedItem[];
  sibling_competences: ContextSibling[];
  company_description: string | null;
}

interface GeneratedItem {
  title: string;
  format: string | null;
  link: string | null;
  study_time: number | null;
  comment: string | null;
  material_type: string;
  skill_level: string;
}

/** Search + filter only appear once the list passes this many rows, so a
 * tenant with three specs doesn't see them. Mirrors the threshold used by
 * the group/indicators picker (HRP-114). */
const LINKED_LIST_FILTER_THRESHOLD = 15;

export function MaterialsAIDialog({
  competenceId,
  open,
  onOpenChange,
  skillLevels,
  onSaved,
}: MaterialsAIDialogProps) {
  const t = useTranslations("competences");
  const tc = useTranslations("common");
  const tRef = useTranslations("reference");
  const [phase, setPhase] = useState<"brief" | "review">("brief");
  const [options, setOptions] = useState<MaterialsContextOptions | null>(null);
  const [optionsLoading, setOptionsLoading] = useState(false);

  const [selectedLevelIds, setSelectedLevelIds] = useState<Set<string>>(
    () => new Set(skillLevels.map((l) => l.id)),
  );
  const [selectedIndicatorIds, setSelectedIndicatorIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [selectedSpecIds, setSelectedSpecIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [selectedDivisionIds, setSelectedDivisionIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [selectedSiblingIds, setSelectedSiblingIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [includeCompanyDesc, setIncludeCompanyDesc] = useState(true);

  const [refinement, setRefinement] = useState("");
  const [countPerLevel, setCountPerLevel] = useState(3);
  const [generating, setGenerating] = useState(false);
  const [items, setItems] = useState<GeneratedItem[]>([]);
  const [kept, setKept] = useState<Set<number>>(() => new Set());
  const [saving, setSaving] = useState(false);

  // Reset to brief when the dialog reopens. Selection state is repopulated
  // when the context-options endpoint resolves below so we don't briefly
  // render a brief with an empty linked-spec set.
  useEffect(() => {
    if (open) {
      setPhase("brief");
      setItems([]);
      setKept(new Set());
    }
  }, [open, competenceId]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setOptionsLoading(true);
    api
      .get<MaterialsContextOptions>(
        `/competences/${competenceId}/ai-generate-materials/context-options`,
      )
      .then((opts) => {
        if (cancelled) return;
        setOptions(opts);
        // Defaults per spec:
        // - all skill levels checked
        // - all indicators checked
        // - linked specs checked
        // - linked divisions checked
        // - sibling competences UNCHECKED
        // - company_description ON when one is set on the tenant
        setSelectedLevelIds(new Set(skillLevels.map((l) => l.id)));
        setSelectedIndicatorIds(new Set(opts.indicators.map((i) => i.id)));
        setSelectedSpecIds(
          new Set(opts.specializations.filter((s) => s.is_linked).map((s) => s.id)),
        );
        setSelectedDivisionIds(
          new Set(opts.divisions.filter((d) => d.is_linked).map((d) => d.id)),
        );
        setSelectedSiblingIds(new Set());
        setIncludeCompanyDesc(Boolean(opts.company_description));
      })
      .catch((err) => {
        if (!cancelled) {
          toast.error(
            err instanceof Error ? err.message : t("errorLoadContextOptions"),
          );
        }
      })
      .finally(() => {
        if (!cancelled) setOptionsLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, competenceId]);

  // HRP-479: the title↔id map stays on the RAW stored titles — the model
  // echoes back the level names it was given in the prompt (which come from
  // the DB), and the matched id is what ends up in the save payload. Never
  // key this map by a localized label.
  const levelIdByTitle = useMemo(() => {
    const map = new Map<string, string>();
    skillLevels.forEach((l) => map.set(l.title.toLowerCase(), l.id));
    return map;
  }, [skillLevels]);

  // Display-only counterpart: id → localized label (origin levels resolve
  // through the catalog, tenant levels fall back to their stored title).
  const levelLabelById = useMemo(() => {
    const map = new Map<string, string>();
    skillLevels.forEach((l) => map.set(l.id, skillLevelLabel(tRef, l)));
    return map;
  }, [skillLevels, tRef]);

  const indicatorsByLevel = useMemo(() => {
    const map = new Map<string, ContextIndicator[]>();
    if (!options) return map;
    for (const ind of options.indicators) {
      const key = ind.skill_level_id ?? "_unknown";
      const bucket = map.get(key) ?? [];
      bucket.push(ind);
      map.set(key, bucket);
    }
    return map;
  }, [options]);

  function toggleSet(setter: typeof setSelectedLevelIds, id: string) {
    setter((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const competenceName =
    options?.competence.title ?? t("matAiCompetenceFallback");
  const materialsTotal =
    selectedLevelIds.size > 0 ? selectedLevelIds.size * countPerLevel : 0;
  const minimalContext =
    selectedIndicatorIds.size === 0 &&
    selectedSpecIds.size === 0 &&
    selectedDivisionIds.size === 0 &&
    selectedSiblingIds.size === 0 &&
    !(includeCompanyDesc && options?.company_description);

  async function handleGenerate() {
    if (selectedLevelIds.size === 0) {
      toast.error(t("errorPickSkillLevel"));
      return;
    }
    setGenerating(true);
    try {
      const body: Record<string, unknown> = {
        skill_level_ids: Array.from(selectedLevelIds),
        count_per_level: countPerLevel,
        // Always send explicit arrays (possibly empty) so the backend knows
        // the operator deliberately deselected something rather than
        // falling back to legacy auto-pick defaults.
        specialization_ids: Array.from(selectedSpecIds),
        indicator_ids: Array.from(selectedIndicatorIds),
        division_ids: Array.from(selectedDivisionIds),
        sibling_competence_ids: Array.from(selectedSiblingIds),
        include_company_description: includeCompanyDesc,
      };
      if (refinement.trim().length > 0) {
        body.refinement = refinement.trim();
      }
      const res = await api.post<GeneratedItem[]>(
        `/competences/${competenceId}/ai-generate-materials`,
        body,
      );
      setItems(res);
      setKept(new Set(res.map((_, idx) => idx)));
      setPhase("review");
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.detail || err.message
          : err instanceof Error
            ? err.message
            : t("errorGenerationFailed");
      toast.error(String(msg));
    } finally {
      setGenerating(false);
    }
  }

  function toggleKept(idx: number) {
    setKept((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  }

  async function handleSave() {
    const rows = items
      .map((it, idx) => ({ it, idx }))
      .filter(({ idx }) => kept.has(idx))
      .map(({ it }) => {
        const matchedId = levelIdByTitle.get(it.skill_level.toLowerCase());
        if (!matchedId) return null;
        return {
          title: it.title,
          format: it.format,
          link: it.link,
          study_time: it.study_time,
          comment: it.comment,
          material_type: it.material_type,
          sort_index: 0,
          skill_level_id: matchedId,
        };
      })
      .filter((x): x is NonNullable<typeof x> => x !== null);

    if (rows.length === 0) {
      toast.error(t("errorPickMaterial"));
      return;
    }

    setSaving(true);
    try {
      const created = await api.post<Material[]>(
        `/competences/${competenceId}/materials/bulk`,
        { materials: rows },
      );
      toast.success(t("toastMaterialsSaved", { count: created.length }));
      onSaved(created.map((m) => m.id));
      onOpenChange(false);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.detail || err.message
          : err instanceof Error
            ? err.message
            : t("errorSave");
      toast.error(String(msg));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="materials-gen-modal"
        className="max-w-3xl max-h-[90vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            {t("matAiTitle", { name: competenceName })}
          </DialogTitle>
        </DialogHeader>

        {phase === "brief" && (
          <div className="space-y-5">
            {/* ---- Generation parameters ---- */}
            <section
              data-testid="materials-gen-section-parameters"
              className="space-y-4"
            >
              <div className="space-y-1.5">
                <Label className="text-xs font-medium">
                  {t("matAiSkillLevels")}
                </Label>
                <p className="text-xs text-muted-foreground">
                  {t("matAiSkillLevelsHint")}
                </p>
                {skillLevels.length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    {t("matAiNoSkillLevels")}
                  </p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {skillLevels.map((lvl) => {
                      const checked = selectedLevelIds.has(lvl.id);
                      return (
                        <label
                          key={lvl.id}
                          data-testid={`materials-gen-skill-level-${lvl.id}`}
                          className={
                            "flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs " +
                            (checked
                              ? "border-primary bg-primary/10 text-foreground"
                              : "border-input bg-background text-muted-foreground hover:text-foreground")
                          }
                        >
                          <Checkbox
                            checked={checked}
                            onCheckedChange={() =>
                              toggleSet(setSelectedLevelIds, lvl.id)
                            }
                          />
                          <span>{skillLevelLabel(tRef, lvl)}</span>
                        </label>
                      );
                    })}
                  </div>
                )}
              </div>

              <div className="space-y-1.5">
                <Label
                  htmlFor="materials-gen-per-level-input"
                  className="text-xs font-medium"
                >
                  {t("matAiPerLevel")}
                </Label>
                <p className="text-xs text-muted-foreground">
                  {t("matAiPerLevelHint")}
                </p>
                <input
                  id="materials-gen-per-level-input"
                  data-testid="materials-gen-per-level-input"
                  type="number"
                  min={1}
                  max={10}
                  value={countPerLevel}
                  onChange={(e) =>
                    setCountPerLevel(
                      Math.max(1, Math.min(10, Number(e.target.value) || 1)),
                    )
                  }
                  className="w-20 rounded-md border border-input bg-background px-2 py-1 text-sm"
                />
              </div>
            </section>

            {/* ---- Context ---- */}
            <section
              data-testid="materials-gen-section-context"
              className="space-y-4 rounded-md border border-dashed p-4"
            >
              <header className="space-y-0.5">
                <h3 className="text-sm font-semibold">
                  {t("matAiContextTitle")}
                </h3>
                <p className="text-xs text-muted-foreground">
                  {t("matAiContextHint")}
                </p>
              </header>

              {optionsLoading || !options ? (
                <p className="text-xs text-muted-foreground">
                  {t("matAiLoadingContext")}
                </p>
              ) : (
                <>
                  <CompetenceInfoBlock competence={options.competence} />

                  <IndicatorsSection
                    indicators={options.indicators}
                    indicatorsByLevel={indicatorsByLevel}
                    levelLabelById={levelLabelById}
                    selectedLevelIds={selectedLevelIds}
                    selectedIndicatorIds={selectedIndicatorIds}
                    onToggle={(id) =>
                      toggleSet(setSelectedIndicatorIds, id)
                    }
                  />

                  <LinkedAwareSection
                    sectionId="specializations"
                    title={t("sectionSpecializations")}
                    items={options.specializations}
                    selectedIds={selectedSpecIds}
                    onToggle={(id) => toggleSet(setSelectedSpecIds, id)}
                    linkedTooltip={t("matAiLinkedThroughCompetence")}
                  />

                  <LinkedAwareSection
                    sectionId="divisions"
                    title={t("sectionDivisions")}
                    items={options.divisions}
                    selectedIds={selectedDivisionIds}
                    onToggle={(id) => toggleSet(setSelectedDivisionIds, id)}
                    linkedTooltip={t("matAiLinkedThroughSpecsPositions")}
                  />

                  {options.sibling_competences.length > 0 ? (
                    <SiblingCompetencesSection
                      items={options.sibling_competences}
                      selectedIds={selectedSiblingIds}
                      onToggle={(id) => toggleSet(setSelectedSiblingIds, id)}
                    />
                  ) : null}

                  {options.company_description ? (
                    <label
                      data-testid="materials-gen-section-company_description"
                      className="flex items-start gap-2 rounded-md border bg-muted/20 px-3 py-2"
                    >
                      <Checkbox
                        checked={includeCompanyDesc}
                        onCheckedChange={(v) =>
                          setIncludeCompanyDesc(Boolean(v))
                        }
                        className="mt-0.5"
                        data-testid="materials-gen-company-description-toggle"
                      />
                      <span className="text-sm">
                        <span className="font-medium">
                          {t("matAiIncludeCompanyDescription")}
                        </span>
                        <span className="block text-xs text-muted-foreground">
                          {options.company_description}
                        </span>
                      </span>
                    </label>
                  ) : null}
                </>
              )}
            </section>

            {/* ---- Refinement ---- */}
            <div className="space-y-1.5">
              <Label
                htmlFor="materials-gen-refinement"
                className="text-xs font-medium"
              >
                {t("matAiRefinement")}
              </Label>
              <Textarea
                id="materials-gen-refinement"
                data-testid="materials-gen-refinement"
                value={refinement}
                onChange={(e) => setRefinement(e.target.value)}
                rows={3}
                placeholder={t("matAiRefinementPlaceholder")}
              />
            </div>

            {/* ---- Summary ---- */}
            <div
              data-testid="materials-gen-summary"
              aria-live="polite"
              className="rounded-md border bg-muted/20 px-3 py-2 text-xs text-muted-foreground"
            >
              {t.rich("matAiSummaryLine", {
                total: materialsTotal,
                levels: selectedLevelIds.size,
                perLevel: countPerLevel,
                name: (chunks) => (
                  <span className="font-medium text-foreground">{chunks}</span>
                ),
                competence: competenceName,
              })}
              <br />
              {includeCompanyDesc && options?.company_description
                ? t("matAiSummaryContextWithCompany", {
                    indicators: selectedIndicatorIds.size,
                    specializations: selectedSpecIds.size,
                    divisions: selectedDivisionIds.size,
                    siblings: selectedSiblingIds.size,
                  })
                : t("matAiSummaryContext", {
                    indicators: selectedIndicatorIds.size,
                    specializations: selectedSpecIds.size,
                    divisions: selectedDivisionIds.size,
                    siblings: selectedSiblingIds.size,
                  })}
              {minimalContext ? (
                <span className="mt-1 block text-amber-700 dark:text-amber-300">
                  {t("matAiMinimalContext")}
                </span>
              ) : null}
            </div>
          </div>
        )}

        {phase === "review" && (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
              {items.length === 0
                ? t("matAiNoItems")
                : t("matAiReviewHint", {
                    kept: items.filter((_, idx) => kept.has(idx)).length,
                    total: items.length,
                  })}
            </p>
            <div className="max-h-[480px] space-y-2 overflow-y-auto pr-1">
              {items.map((it, idx) => {
                const checked = kept.has(idx);
                return (
                  <label
                    key={`${it.title}-${idx}`}
                    data-testid={`materials-gen-review-item-${idx}`}
                    className={
                      "flex items-start gap-3 rounded-md border p-3 text-sm " +
                      (checked
                        ? "border-primary/50 bg-primary/5"
                        : "border-input bg-muted/30 text-muted-foreground")
                    }
                  >
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => toggleKept(idx)}
                      className="mt-0.5"
                    />
                    <div className="flex-1 space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{it.title}</span>
                        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase text-muted-foreground">
                          {it.material_type}
                        </span>
                        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                          {levelLabelById.get(
                            levelIdByTitle.get(it.skill_level.toLowerCase()) ?? "",
                          ) ?? it.skill_level}
                        </span>
                      </div>
                      <p className="text-xs leading-snug">{it.comment}</p>
                      <div className="flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
                        {it.format && <span>{it.format}</span>}
                        {it.study_time != null && <span>{it.study_time}h</span>}
                        {it.link && (
                          <a
                            href={it.link}
                            target="_blank"
                            rel="noreferrer"
                            className="text-primary underline"
                          >
                            {/* eslint-disable react/jsx-no-literals -- accepted F2 debt (HRP-476) */}
                            link
                            {/* eslint-enable react/jsx-no-literals */}
                          </a>
                        )}
                      </div>
                    </div>
                  </label>
                );
              })}
            </div>
          </div>
        )}

        <DialogFooter>
          {phase === "brief" && (
            <>
              <Button
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={generating}
                data-testid="materials-gen-cancel"
              >
                {tc("cancel")}
              </Button>
              <Button
                data-testid="materials-gen-submit"
                onClick={handleGenerate}
                disabled={
                  generating ||
                  optionsLoading ||
                  selectedLevelIds.size === 0 ||
                  !options
                }
              >
                {generating ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    {t("matAiGenerating")}
                  </>
                ) : (
                  <>
                    <Sparkles className="mr-2 h-4 w-4" />
                    {t("matAiGenerate")}
                  </>
                )}
              </Button>
            </>
          )}
          {phase === "review" && (
            <>
              <Button
                variant="outline"
                onClick={() => setPhase("brief")}
                disabled={saving}
              >
                <X className="mr-2 h-4 w-4" />
                {t("matAiBackToBrief")}
              </Button>
              <Button
                data-testid="materials-gen-save"
                onClick={handleSave}
                disabled={saving || kept.size === 0}
              >
                {saving
                  ? t("savingEllipsis")
                  : t("matAiSaveCount", { count: kept.size })}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ----- Sub-components below -----

function CompetenceInfoBlock({
  competence,
}: {
  competence: ContextCompetence;
}) {
  const t = useTranslations("competences");
  return (
    <section
      data-testid="materials-gen-section-competence_info"
      className="space-y-1 rounded-md border bg-muted/20 px-3 py-2 text-sm"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">{competence.title}</span>
        <span className="text-[10px] uppercase text-muted-foreground">
          {t("matAiAlwaysIncluded")}
        </span>
      </div>
      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
        {competence.type ? <span>{competence.type}</span> : null}
        {competence.group ? (
          <span>{t("matAiGroupPrefix", { title: competence.group.title })}</span>
        ) : null}
      </div>
      {competence.description ? (
        <p className="text-xs text-muted-foreground">{competence.description}</p>
      ) : null}
    </section>
  );
}

function IndicatorsSection({
  indicators,
  indicatorsByLevel,
  levelLabelById,
  selectedLevelIds,
  selectedIndicatorIds,
  onToggle,
}: {
  indicators: ContextIndicator[];
  indicatorsByLevel: Map<string, ContextIndicator[]>;
  levelLabelById: Map<string, string>;
  selectedLevelIds: Set<string>;
  selectedIndicatorIds: Set<string>;
  onToggle: (id: string) => void;
}) {
  const t = useTranslations("competences");
  if (indicators.length === 0) {
    return (
      <section
        data-testid="materials-gen-section-indicators"
        className="space-y-1.5"
      >
        <header className="flex items-baseline justify-between">
          <Label className="text-xs font-medium">
            {t("sectionIndicators")}
          </Label>
        </header>
        <p className="text-xs text-muted-foreground">
          {t("matAiNoIndicators")}
        </p>
      </section>
    );
  }

  return (
    <section
      data-testid="materials-gen-section-indicators"
      className="space-y-2"
    >
      <header className="flex items-baseline justify-between">
        <Label className="text-xs font-medium">
          {t("matAiIndicatorsCounter", {
            selected: selectedIndicatorIds.size,
            total: indicators.length,
          })}
        </Label>
      </header>
      <div className="space-y-2">
        {Array.from(indicatorsByLevel.entries()).map(([levelKey, list]) => {
          // `skill_level_title` is a flat string denormalized into the
          // context payload (no i18n_key) — it stays verbatim.
          const levelTitle =
            levelLabelById.get(levelKey) ??
            list[0]?.skill_level_title ??
            t("matAiLevelOther");
          const levelActive =
            levelKey === "_unknown" || selectedLevelIds.has(levelKey);
          return (
            <fieldset
              key={levelKey}
              className={
                "space-y-1.5 " + (levelActive ? "" : "opacity-50")
              }
            >
              <legend className="text-[11px] uppercase tracking-wide text-muted-foreground">
                {levelTitle}
              </legend>
              <div className="flex flex-wrap gap-2">
                {list.map((ind) => {
                  const checked = selectedIndicatorIds.has(ind.id);
                  return (
                    <Tooltip key={ind.id}>
                      <TooltipTrigger
                        render={
                          <label
                            data-testid={`materials-gen-context-chip-indicator-${ind.id}`}
                            className={
                              "flex max-w-[260px] cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1 text-xs " +
                              (checked
                                ? "border-primary bg-primary/10 text-foreground"
                                : "border-input bg-background text-muted-foreground hover:text-foreground")
                            }
                          >
                            <Checkbox
                              checked={checked}
                              onCheckedChange={() => onToggle(ind.id)}
                            />
                            <span className="truncate">{ind.title}</span>
                          </label>
                        }
                      />
                      <TooltipContent side="top" className="max-w-sm text-xs">
                        {ind.title}
                      </TooltipContent>
                    </Tooltip>
                  );
                })}
              </div>
            </fieldset>
          );
        })}
      </div>
      <p className="text-[11px] text-muted-foreground">
        {t("matAiIndicatorsHint")}
      </p>
    </section>
  );
}

function LinkedAwareSection({
  sectionId,
  title,
  items,
  selectedIds,
  onToggle,
  linkedTooltip,
}: {
  sectionId: "specializations" | "divisions";
  title: string;
  items: ContextLinkedItem[];
  selectedIds: Set<string>;
  onToggle: (id: string) => void;
  linkedTooltip: string;
}) {
  const t = useTranslations("competences");
  const [search, setSearch] = useState("");
  const [linkedOnly, setLinkedOnly] = useState(false);

  const showControls = items.length > LINKED_LIST_FILTER_THRESHOLD;
  const visible = useMemo(() => {
    let list = items;
    if (linkedOnly) list = list.filter((i) => i.is_linked);
    const term = search.trim().toLowerCase();
    if (term) list = list.filter((i) => i.title.toLowerCase().includes(term));
    return list;
  }, [items, linkedOnly, search]);

  const linkedCount = items.filter((i) => i.is_linked).length;

  return (
    <section
      data-testid={`materials-gen-section-${sectionId}`}
      className="space-y-2"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <Label className="text-xs font-medium">
          {title}{" "}
          {linkedCount > 0
            ? t("contextCounterLinked", {
                selected: selectedIds.size,
                total: items.length,
                linked: linkedCount,
              })
            : t("contextCounter", {
                selected: selectedIds.size,
                total: items.length,
              })}
        </Label>
        {showControls ? (
          <div className="flex items-center gap-2">
            <label
              className="flex items-center gap-1 text-[11px] text-muted-foreground"
              data-testid={`materials-gen-context-${sectionId}-filter-linked-only`}
            >
              <Checkbox
                checked={linkedOnly}
                onCheckedChange={(v) => setLinkedOnly(Boolean(v))}
              />
              <span>{t("contextShowLinkedOnly")}</span>
            </label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t("searchShort")}
                className="h-7 w-44 pl-7 text-xs"
                data-testid={`materials-gen-context-${sectionId}-search`}
              />
            </div>
          </div>
        ) : null}
      </header>
      <div
        data-testid={`materials-gen-context-${sectionId}-counter`}
        className="sr-only"
      >
        {selectedIds.size}/{items.length}
      </div>
      {visible.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          {items.length === 0
            ? sectionId === "specializations"
              ? t("matAiNoSpecializationsConfigured")
              : t("matAiNoDivisionsConfigured")
            : t("contextNothingMatchesFilter")}
        </p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {visible.map((it) => {
            const checked = selectedIds.has(it.id);
            const testIdBase =
              sectionId === "specializations" ? "specialization" : "division";
            return (
              <label
                key={it.id}
                data-testid={`materials-gen-context-chip-${testIdBase}-${it.id}`}
                className={
                  "flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs " +
                  (checked
                    ? "border-primary bg-primary/10 text-foreground"
                    : "border-input bg-background text-muted-foreground hover:text-foreground")
                }
              >
                <Checkbox
                  checked={checked}
                  onCheckedChange={() => onToggle(it.id)}
                />
                <span>{it.title}</span>
                {it.is_linked ? (
                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <span
                          data-testid={`materials-gen-context-chip-${testIdBase}-${it.id}-linked-marker`}
                          className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-primary/15 text-primary"
                        >
                          <Link2 className="h-3 w-3" />
                        </span>
                      }
                    />
                    <TooltipContent side="top" className="text-xs">
                      {linkedTooltip}
                    </TooltipContent>
                  </Tooltip>
                ) : null}
              </label>
            );
          })}
        </div>
      )}
    </section>
  );
}

function SiblingCompetencesSection({
  items,
  selectedIds,
  onToggle,
}: {
  items: ContextSibling[];
  selectedIds: Set<string>;
  onToggle: (id: string) => void;
}) {
  const t = useTranslations("competences");
  return (
    <section
      data-testid="materials-gen-section-sibling_competences"
      className="space-y-2"
    >
      <header className="flex items-baseline justify-between">
        <Label className="text-xs font-medium">
          {t("matAiSiblingsCounter", {
            selected: selectedIds.size,
            total: items.length,
          })}
        </Label>
      </header>
      <p className="text-[11px] text-muted-foreground">
        {t("matAiSiblingsHint")}
      </p>
      <div className="flex flex-wrap gap-2">
        {items.map((it) => {
          const checked = selectedIds.has(it.id);
          return (
            <label
              key={it.id}
              data-testid={`materials-gen-context-chip-sibling_competence-${it.id}`}
              className={
                "flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs " +
                (checked
                  ? "border-primary bg-primary/10 text-foreground"
                  : "border-input bg-background text-muted-foreground hover:text-foreground")
              }
            >
              <Checkbox
                checked={checked}
                onCheckedChange={() => onToggle(it.id)}
              />
              <span>{it.title}</span>
            </label>
          );
        })}
      </div>
    </section>
  );
}
