"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { api, ApiError } from "@/lib/api";
import type {
  AnswerOption,
  AnswerScaleDetail,
  DetailedQuestion,
  DetailedResultsResponse,
} from "@/lib/types";
import {
  dictionaryItemLabel,
  scaleOptionLabel,
  skillLevelLabel,
} from "@/lib/reference-labels";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatDateTime as formatIsoDateTime } from "@/lib/date-format";

/** Participant role codes → keys in the `assessments` i18n namespace. */
const ROLE_KEYS: Record<string, string> = {
  self: "roleSelf",
  manager: "roleManager",
  peer: "rolePeer",
  subordinate: "roleSubordinate",
  external: "roleExternal",
};

function roleLabel(t: (key: string) => string, role: string): string {
  const key = ROLE_KEYS[role];
  return key ? t(key) : role.charAt(0).toUpperCase() + role.slice(1);
}

function formatPercent(value: number | null): string {
  if (value === null) return "—";
  return `${Math.round(value)}%`;
}

function formatDateTime(iso: string): string {
  return formatIsoDateTime(iso, iso);
}

export interface AssessmentDetailedResultsProps {
  assessmentId: string;
  /** Show the block only when the parent Results card is rendered. */
  visible: boolean;
  /** HRP-185: scale snapshot so the per-indicator Total picker can list
   *  the available answer options. */
  scale: AnswerScaleDetail | null;
  /** HRP-185: true while a reviewer is actively editing Totals (the
   *  backend lock is on the assessment row). */
  calibrationInProgress: boolean;
  /** Only managers / admins / platform admins can drive calibration. */
  canManage: boolean;
  /** Notifies the parent so it can refresh after start / save / cancel. */
  onCalibrationChange: () => Promise<void> | void;
}

export function AssessmentDetailedResults({
  assessmentId,
  visible,
  scale,
  calibrationInProgress,
  canManage,
  onCalibrationChange,
}: AssessmentDetailedResultsProps) {
  const t = useTranslations("assessments");
  const tc = useTranslations("common");
  const tRef = useTranslations("reference");
  const [state, setState] = useState<{
    loading: boolean;
    error: string | null;
    data: DetailedResultsResponse | null;
  }>({ loading: visible, error: null, data: null });
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [editMode, setEditMode] = useState(false);
  // Pending overrides while editing — keyed by indicator id; null marks
  // a reset to the computed Total. Once Save lands the parent reloads
  // and the data carries `is_calibrated`.
  const [pendingTotals, setPendingTotals] = useState<Record<string, string>>({});
  const [confirmStart, setConfirmStart] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [busy, setBusy] = useState(false);
  // HRP-185 REDO #3: Cancel calibration from the post-Save state doesn't
  // flip ``calibrationInProgress`` (it was already false), so the deps on
  // the fetch effect wouldn't refire and Detailed results kept showing
  // the calibrated values until F5. Bump this counter on every save /
  // cancel so the effect refetches regardless of the lock state.
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    api
      .get<DetailedResultsResponse>(`/assessments/${assessmentId}/detailed-results`)
      .then((res) => {
        if (cancelled) return;
        setState({ loading: false, error: null, data: res });
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 403) {
          setState({ loading: false, error: null, data: null });
        } else {
          setState({
            loading: false,
            error:
              err instanceof Error ? err.message : t("errorLoadDetailedResults"),
            data: null,
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [assessmentId, visible, calibrationInProgress, refreshKey, t]);

  // Enter edit mode whenever the backend reports calibration_in_progress.
  // Expand every competence so the reviewer can see every indicator at
  // once — the spec calls for the full survey while calibrating.
  //
  // HRP-185 REDO: pre-seed the Select with the auto-computed Total so
  // each row opens at the same answer the badge was showing instead of
  // the empty "Total" placeholder. Existing calibrated overrides win
  // over the auto pick.
  useEffect(() => {
    if (calibrationInProgress && state.data) {
      setEditMode(true);
      setExpanded(new Set(state.data.competences.map((c) => c.competence_id)));
      const seeded: Record<string, string> = {};
      for (const comp of state.data.competences) {
        for (const sl of comp.skill_levels) {
          for (const q of sl.questions) {
            const seed = q.calibrated_answer_option_id ?? q.overall_answer_option_id;
            if (seed) seeded[q.indicator_id] = seed;
          }
        }
      }
      setPendingTotals(seeded);
    } else {
      setEditMode(false);
      setPendingTotals({});
    }
  }, [calibrationInProgress, state.data]);

  const { loading, error, data } = state;
  const competences = useMemo(() => data?.competences ?? [], [data]);
  const hasCalibratedTotals = useMemo(
    () =>
      competences.some((c) =>
        c.skill_levels.some((sl) => sl.questions.some((q) => q.is_calibrated)),
      ),
    [competences],
  );

  const scaleOptions = useMemo<AnswerOption[]>(() => {
    if (!scale) return [];
    return [...scale.options]
      .filter((o) => !o.is_neutral)
      .sort((a, b) => a.sort_index - b.sort_index);
  }, [scale]);

  // HRP-185 REDO: enable Save only when at least one Total moved away
  // from what was originally on the row (auto-computed or already
  // calibrated). Pre-seeded values that match the source don't count as
  // "changed", otherwise reopening calibration would immediately enable
  // Save with no real input.
  function totalChanged(): boolean {
    if (!data) return false;
    for (const comp of data.competences) {
      for (const sl of comp.skill_levels) {
        for (const q of sl.questions) {
          const baseline = q.calibrated_answer_option_id ?? q.overall_answer_option_id;
          const current = pendingTotals[q.indicator_id];
          if (current && current !== baseline) return true;
        }
      }
    }
    return false;
  }

  async function startCalibration() {
    setBusy(true);
    try {
      await api.post(`/assessments/${assessmentId}/calibration/start`, {});
      await onCalibrationChange();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorCalibrationStart"));
    } finally {
      setBusy(false);
      setConfirmStart(false);
    }
  }

  async function saveCalibration() {
    setBusy(true);
    try {
      // HRP-185 REDO: only send totals the reviewer actually moved off
      // the baseline (auto-computed or already calibrated). Sending the
      // pre-seeded picks would persist every indicator as "calibrated"
      // even when the operator hadn't touched anything.
      const baselineByIndicator = new Map<string, string | null>();
      if (data) {
        for (const comp of data.competences) {
          for (const sl of comp.skill_levels) {
            for (const q of sl.questions) {
              baselineByIndicator.set(
                q.indicator_id,
                q.calibrated_answer_option_id ?? q.overall_answer_option_id,
              );
            }
          }
        }
      }
      const totals = Object.entries(pendingTotals)
        .filter(([indicator_id, val]) => {
          if (!val) return false;
          const baseline = baselineByIndicator.get(indicator_id) ?? null;
          return val !== baseline;
        })
        .map(([indicator_id, answer_option_id]) => ({
          indicator_id,
          answer_option_id,
        }));
      await api.post(`/assessments/${assessmentId}/calibration/save`, {
        totals,
      });
      setPendingTotals({});
      setRefreshKey((k) => k + 1);
      await onCalibrationChange();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorCalibrationSave"));
    } finally {
      setBusy(false);
    }
  }

  async function cancelCalibration() {
    setBusy(true);
    try {
      await api.post(`/assessments/${assessmentId}/calibration/cancel`, {});
      setPendingTotals({});
      setRefreshKey((k) => k + 1);
      await onCalibrationChange();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorCalibrationCancel"));
    } finally {
      setBusy(false);
      setConfirmCancel(false);
    }
  }

  if (!visible) return null;
  if (loading) {
    return (
      <Card data-testid="assessment-detailed-results">
        <CardHeader>
          <CardTitle className="text-base">{t("detailedResults")}</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          {t("loadingEllipsis")}
        </CardContent>
      </Card>
    );
  }
  if (error) {
    return (
      <Card data-testid="assessment-detailed-results">
        <CardHeader>
          <CardTitle className="text-base">{t("detailedResults")}</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-red-600">{error}</CardContent>
      </Card>
    );
  }
  if (competences.length === 0) return null;

  function toggle(compId: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(compId)) next.delete(compId);
      else next.add(compId);
      return next;
    });
  }

  // HRP-479: denormalized answers carry the stable option code next to
  // the snapshot title — seeded-scale answers localize, tenant options
  // (opt_N/neutral codes, absent from the catalog) fall back verbatim.
  function answerLabel(code: string | null, title: string | null) {
    if (title === null) return null;
    return code ? scaleOptionLabel(tRef, { code, title }) : title;
  }

  function renderQuestionTotal(q: DetailedQuestion) {
    const overrideId = pendingTotals[q.indicator_id];
    const baseline = q.calibrated_answer_option_id ?? q.overall_answer_option_id;
    // HRP-185 REDO: a pre-seeded option that still matches an
    // *uncalibrated* baseline stays unchipped — the chip calls out manual
    // overrides. HRP-330: an indicator calibrated in a previous session
    // keeps its chip when calibration is reopened.
    const showCalibratedChip =
      q.is_calibrated ||
      (editMode && overrideId && baseline && overrideId !== baseline);
    if (editMode) {
      // HRP-185 REDO: BaseUI's SelectValue doesn't auto-render the
      // matching SelectItem children, so we pass the option title
      // explicitly — otherwise the trigger would display the raw UUID
      // value after a pick.
      const selectedOption =
        scaleOptions.find((opt) => opt.id === overrideId) ?? null;
      const selectedTitle = selectedOption
        ? scaleOptionLabel(tRef, selectedOption)
        : null;
      return (
        <div className="flex items-center gap-2">
          <Select
            value={overrideId ?? ""}
            onValueChange={(val) =>
              setPendingTotals((prev) => ({ ...prev, [q.indicator_id]: val }))
            }
          >
            <SelectTrigger
              className="h-7 w-40 text-xs"
              data-testid={`calibrate-total-${q.indicator_id}`}
            >
              <SelectValue placeholder={t("total")}>{selectedTitle}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {scaleOptions.map((opt) => (
                <SelectItem key={opt.id} value={opt.id}>
                  {scaleOptionLabel(tRef, opt)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {showCalibratedChip && (
            <Badge
              variant="outline"
              className="border-amber-300 text-amber-700"
              data-testid={`calibrate-chip-${q.indicator_id}`}
            >
              {t("calibratedChip")}
            </Badge>
          )}
        </div>
      );
    }
    return (
      <div className="flex items-center gap-2">
        <span className="font-semibold">
          {q.all_dont_know
            ? "—"
            : answerLabel(q.overall_answer_code, q.overall_answer_title) ??
              (q.overall_percent !== null ? formatPercent(q.overall_percent) : "—")}
        </span>
        {showCalibratedChip && (
          <Badge
            variant="outline"
            className="border-amber-300 text-amber-700"
            data-testid={`calibrate-chip-${q.indicator_id}`}
          >
            {t("calibratedChip")}
          </Badge>
        )}
      </div>
    );
  }

  return (
    <Card data-testid="assessment-detailed-results">
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle className="text-base">{t("detailedResults")}</CardTitle>
        {canManage && !editMode && (
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              data-testid="detailed-results-btn-calibrate"
              disabled={busy}
              onClick={() => setConfirmStart(true)}
            >
              {t("calibrate")}
            </Button>
            {hasCalibratedTotals && (
              <Button
                size="sm"
                variant="outline"
                data-testid="detailed-results-btn-cancel-calibration"
                disabled={busy}
                onClick={() => setConfirmCancel(true)}
              >
                {t("cancelCalibration")}
              </Button>
            )}
          </div>
        )}
        {canManage && editMode && (
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="ghost"
              data-testid="detailed-results-btn-discard"
              disabled={busy}
              onClick={() => setConfirmCancel(true)}
            >
              {tc("cancel")}
            </Button>
            <Button
              size="sm"
              data-testid="detailed-results-btn-save-calibration"
              disabled={busy || !totalChanged()}
              onClick={saveCalibration}
            >
              {t("saveCalibration")}
            </Button>
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {competences.map((comp) => {
          const isOpen = expanded.has(comp.competence_id) || editMode;
          return (
            <div
              key={comp.competence_id}
              className="rounded-lg border"
              data-testid={`detailed-results-competence-${comp.competence_id}`}
            >
              <button
                type="button"
                onClick={() => !editMode && toggle(comp.competence_id)}
                className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left disabled:cursor-default"
                aria-expanded={isOpen}
                disabled={editMode}
                data-testid={`detailed-results-competence-${comp.competence_id}-toggle`}
              >
                <div className="flex flex-1 flex-wrap items-center gap-2">
                  {comp.competence_type_title && (
                    <Badge variant="outline" className="font-normal">
                      {dictionaryItemLabel(tRef, {
                        type: "competence_type",
                        title: comp.competence_type_title,
                        i18n_key: comp.competence_type_i18n_key,
                      })}
                    </Badge>
                  )}
                  <span className="font-medium">{comp.competence_title}</span>
                  {comp.required_skill_level_title && (
                    <Badge variant="secondary" className="font-normal">
                      {t("requiredLevel", {
                        level: skillLevelLabel(tRef, {
                          title: comp.required_skill_level_title,
                          i18n_key: comp.required_skill_level_i18n_key,
                        }),
                      })}
                    </Badge>
                  )}
                </div>
                <div className="flex items-center gap-3 text-sm">
                  <span
                    className="font-semibold"
                    data-testid={`detailed-results-competence-${comp.competence_id}-percent`}
                  >
                    {comp.all_dont_know ? "—" : formatPercent(comp.percent)}
                  </span>
                  {!editMode &&
                    (isOpen ? (
                      <ChevronDown className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
                    ))}
                </div>
              </button>
              {isOpen && (
                <div className="space-y-4 border-t px-4 py-3">
                  {comp.skill_levels.map((sl) => (
                    <div
                      key={sl.skill_level_id ?? "unscoped"}
                      data-testid={`detailed-results-level-${sl.skill_level_id ?? "unscoped"}`}
                    >
                      <div className="flex items-center justify-between text-sm">
                        <div className="font-medium">
                          {sl.skill_level_title
                            ? skillLevelLabel(tRef, {
                                title: sl.skill_level_title,
                                i18n_key: sl.skill_level_i18n_key,
                              })
                            : t("withoutLevel")}
                        </div>
                        <div className="text-muted-foreground">
                          {t("percentForSkillLevel")}{" "}
                          <span className="font-medium text-foreground">
                            {sl.all_dont_know
                              ? "—"
                              : formatPercent(sl.percent_for_skill_level)}
                          </span>
                        </div>
                      </div>
                      <div className="mt-2 space-y-3">
                        {sl.questions.map((q) => (
                          <div
                            key={q.indicator_id}
                            className="rounded-md border bg-muted/30 px-3 py-2"
                            data-testid={`detailed-results-question-${q.indicator_id}`}
                          >
                            <div className="text-sm font-medium">{q.indicator_title}</div>
                            <div className="mt-2 space-y-1 text-sm">
                              {q.roles.map((r) => (
                                <div
                                  key={`${q.indicator_id}-${r.role}`}
                                  className="flex items-center justify-between gap-2"
                                  data-testid={`detailed-results-question-${q.indicator_id}-role-${r.role}`}
                                >
                                  <span className="text-muted-foreground">
                                    {roleLabel(t, r.role)}
                                  </span>
                                  <span
                                    className={
                                      r.is_neutral
                                        ? "text-muted-foreground/70"
                                        : "font-medium"
                                    }
                                  >
                                    {answerLabel(r.answer_code, r.answer_title) ??
                                      "—"}
                                  </span>
                                </div>
                              ))}
                              <div className="flex items-center justify-between gap-2 border-t pt-1 text-sm">
                                <span className="font-medium">{t("total")}</span>
                                {renderQuestionTotal(q)}
                              </div>
                            </div>
                            {q.comments.length > 0 && (
                              <div className="mt-2 space-y-2 border-t pt-2 text-xs">
                                {q.comments.map((c, idx) => (
                                  <div
                                    key={`${q.indicator_id}-cmt-${idx}`}
                                    data-testid={`detailed-results-question-${q.indicator_id}-comment-${idx}`}
                                  >
                                    <div className="flex items-baseline justify-between gap-2 text-muted-foreground">
                                      <span>
                                        {c.user_name ?? "—"}{" "}
                                        <Badge
                                          variant="outline"
                                          className="ml-1 font-normal"
                                        >
                                          {roleLabel(t, c.role)}
                                        </Badge>
                                      </span>
                                      <span>{formatDateTime(c.created_at)}</span>
                                    </div>
                                    <div className="text-foreground">{c.text}</div>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </CardContent>
      <ConfirmDialog
        open={confirmStart}
        onOpenChange={setConfirmStart}
        title={t("calibrateConfirmTitle")}
        description={t("calibrateConfirmDescription")}
        confirmLabel={t("calibrate")}
        cancelLabel={tc("cancel")}
        onConfirm={startCalibration}
        testId="calibrate-confirm-start"
      />
      <ConfirmDialog
        open={confirmCancel}
        onOpenChange={setConfirmCancel}
        title={t("cancelCalibrationTitle")}
        description={t("cancelCalibrationDescription")}
        confirmLabel={t("cancelCalibration")}
        cancelLabel={t("keep")}
        destructive
        onConfirm={cancelCalibration}
        testId="calibrate-confirm-cancel"
      />
    </Card>
  );
}
