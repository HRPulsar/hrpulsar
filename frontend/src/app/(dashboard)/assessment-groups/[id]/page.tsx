"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Check, Pencil, Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { usePermissions } from "@/hooks/use-permissions";
import type {
  AssessmentDetail,
  AssessmentGroupDetail,
  CriteriaUpdate,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CriteriaSummary } from "@/components/assessment/criteria-summary";
import { GroupAnalytics } from "@/components/assessment/analytics/group-analytics";
import { Input } from "@/components/ui/input";
import {
  answerScaleDescription,
  answerScaleLabel,
  assessmentStatusTitle,
  assessmentTypeTitle,
  scaleOptionDescription,
  scaleOptionLabel,
} from "@/lib/reference-labels";
import { scaleOptionSuffix } from "@/lib/scale-option-label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { CriteriaSheet } from "@/components/assessment/criteria-sheet";
import { ScalePickerDialog } from "@/components/assessment/scale-picker-dialog";

function isGroupDraft(group: AssessmentGroupDetail): boolean {
  // The group itself has no status field — the draft window is open as long as
  // every contained assessment is still in draft. Mirrors backend's
  // _assert_criteria_editable per-assessment check applied to the whole group.
  if (!group.assessments.length) return true;
  return group.assessments.every((a) => a.status_code === "draft");
}

export default function AssessmentGroupPage() {
  const { id } = useParams<{ id: string }>();
  const t = useTranslations("assessments");
  const tc = useTranslations("common");
  const tRef = useTranslations("reference");
  const { canManage } = usePermissions();
  const [group, setGroup] = useState<AssessmentGroupDetail | null>(null);
  const [recommendations, setRecommendations] = useState<
    Record<string, { grade_id: string | null; grade_title: string | null; passed: boolean }>
  >({});
  const [filterGradeId, setFilterGradeId] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [criteriaOpen, setCriteriaOpen] = useState(false);
  const [scaleOpen, setScaleOpen] = useState(false);
  const [titleEditing, setTitleEditing] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [savingTitle, setSavingTitle] = useState(false);

  const load = useCallback(async () => {
    try {
      const g = await api.get<AssessmentGroupDetail>(`/assessment-groups/${id}`);
      setGroup(g);

      const doneAssessments = g.assessments.filter((a) => a.status_code === "done");
      if (doneAssessments.length === 0) {
        setRecommendations({});
        return;
      }
      const details = await Promise.all(
        doneAssessments.map((a) =>
          api
            .get<AssessmentDetail>(`/assessments/${a.id}`)
            .then((d) => [a.id, d] as const)
            .catch(() => [a.id, null] as const),
        ),
      );
      const next: Record<
        string,
        { grade_id: string | null; grade_title: string | null; passed: boolean }
      > = {};
      for (const [aid, detail] of details) {
        const rec = detail?.recommendation;
        if (!rec) continue;
        next[aid] = {
          grade_id: rec.recommended_grade_id,
          grade_title: rec.recommended_grade_title,
          passed: rec.recommended_grade_passed,
        };
      }
      setRecommendations(next);
    } catch {
      toast.error(t("errorLoadGroup"));
    } finally {
      setLoading(false);
    }
  }, [id, t]);

  useEffect(() => {
    load();
  }, [load]);

  async function saveCriteria(payload: CriteriaUpdate) {
    await api.put(`/assessment-groups/${id}/criteria`, payload);
    toast.success(t("toastCriteriaSaved"));
    await load();
  }

  async function saveTitle() {
    const next = titleDraft.trim();
    if (!next) {
      toast.error(t("errorTitleEmpty"));
      return;
    }
    setSavingTitle(true);
    try {
      await api.patch(`/assessment-groups/${id}`, { title: next });
      setTitleEditing(false);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorTitleUpdateFailed"));
    } finally {
      setSavingTitle(false);
    }
  }

  async function saveScale(scaleId: string | null) {
    try {
      await api.put(`/assessment-groups/${id}/scale`, { scale_id: scaleId });
      toast.success(t("toastRatingScaleUpdated"));
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorScaleSaveFailed"));
      throw err;
    }
  }

  if (loading) {
    return (
      <div className="py-12 text-center text-muted-foreground">
        {t("loadingEllipsis")}
      </div>
    );
  }
  if (!group) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" render={<Link href="/assessments" />}>
          <ArrowLeft className="mr-1 h-4 w-4" /> {t("backToAssessments")}
        </Button>
        <div className="py-12 text-center text-muted-foreground">
          {t("groupNotFound")}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon-sm" render={<Link href="/assessments" />}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          {titleEditing ? (
            <div className="flex items-center gap-2">
              <Input
                data-testid="group-input-edit-title"
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                className="h-9 max-w-md text-base"
                autoFocus
                disabled={savingTitle}
                maxLength={100}
              />
              <Button
                size="icon-sm"
                onClick={saveTitle}
                disabled={savingTitle}
                data-testid="group-btn-save-title"
              >
                <Check className="h-4 w-4" />
              </Button>
              <Button
                size="icon-sm"
                variant="ghost"
                onClick={() => setTitleEditing(false)}
                disabled={savingTitle}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          ) : (
            <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
              <span>{group.title}</span>
              {canManage && (
                <Button
                  size="icon-sm"
                  variant="ghost"
                  data-testid="group-btn-edit-title"
                  onClick={() => {
                    setTitleDraft(group.title);
                    setTitleEditing(true);
                  }}
                >
                  <Pencil className="h-4 w-4" />
                </Button>
              )}
            </h1>
          )}
          <p className="text-sm text-muted-foreground">
            {group.type_code && group.type_title
              ? assessmentTypeTitle(tRef, {
                  type_code: group.type_code,
                  type_title: group.type_title,
                })
              : group.type_title ?? ""}{" "}
            ·{" "}
            {t("employeesCount", { count: group.assessment_count })}
          </p>
        </div>
      </div>

      <Card data-testid="group-criteria-card">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-base">{t("evaluationCriteria")}</CardTitle>
          {canManage && isGroupDraft(group) && (
            <Button
              data-testid="group-criteria-btn-edit"
              size="sm"
              variant="outline"
              onClick={() => setCriteriaOpen(true)}
            >
              <Pencil className="mr-1 h-4 w-4" />
              {group.criteria_type ? t("change") : t("select")}
            </Button>
          )}
        </CardHeader>
        <CardContent>
          <CriteriaSummary
            criteriaType={group.criteria_type}
            specializationTitle={group.specialization_title}
            gradeTitle={group.grade_title}
            specializationI18nKey={group.specialization_i18n_key}
            gradeI18nKey={group.grade_i18n_key}
            gradeId={group.grade_id}
            competences={group.competences}
            isMassParent
          />
        </CardContent>
      </Card>

      <Card data-testid="group-scale-card">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-base">{t("ratingScale")}</CardTitle>
          {canManage && isGroupDraft(group) && group.scale && (
            <Button
              data-testid="group-scale-btn-change"
              size="sm"
              variant="outline"
              onClick={() => setScaleOpen(true)}
            >
              <Pencil className="mr-1 h-4 w-4" />
              {t("change")}
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {group.scale ? (
            <div className="space-y-2">
              <p className="text-sm font-medium">
                {answerScaleLabel(tRef, group.scale)}
              </p>
              {answerScaleDescription(tRef, group.scale) && (
                <p className="text-xs text-muted-foreground">
                  {answerScaleDescription(tRef, group.scale)}
                </p>
              )}
              <div className="flex flex-wrap gap-2 pt-1">
                {[...group.scale.options]
                  .sort((a, b) => a.sort_index - b.sort_index)
                  .map((opt) => {
                    const suffix = scaleOptionSuffix(t, opt, {
                      showScore: canManage,
                    });
                    return (
                      <Badge
                        key={opt.id}
                        variant="outline"
                        title={scaleOptionDescription(tRef, opt) ?? undefined}
                      >
                        {scaleOptionLabel(tRef, opt)}
                        {suffix && (
                          <span className="ml-1 text-muted-foreground">{suffix}</span>
                        )}
                      </Badge>
                    );
                  })}
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-3 py-4 text-center">
              <p className="text-sm text-muted-foreground">
                {t("noScaleGroup")}
              </p>
              {canManage && isGroupDraft(group) && (
                <Button
                  data-testid="group-scale-btn-add"
                  size="sm"
                  onClick={() => setScaleOpen(true)}
                >
                  <Plus className="mr-1 h-4 w-4" />
                  {t("addScale")}
                </Button>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-base">{t("groupAssessments")}</CardTitle>
          {(() => {
            const gradeOptions = Object.values(recommendations).reduce(
              (acc, rec) => {
                if (rec.grade_id && !acc.find((g) => g.id === rec.grade_id)) {
                  acc.push({ id: rec.grade_id, title: rec.grade_title ?? "—" });
                }
                return acc;
              },
              [] as { id: string; title: string }[],
            );
            if (gradeOptions.length === 0) return null;
            return (
              <Select value={filterGradeId} onValueChange={setFilterGradeId}>
                <SelectTrigger
                  className="w-56"
                  data-testid="assessment-group-filter-grade"
                >
                  <SelectValue placeholder={t("allRecommendedGrades")}>
                    {(value) =>
                      !value
                        ? t("allRecommendedGrades")
                        : gradeOptions.find((g) => g.id === value)?.title ??
                          t("allRecommendedGrades")
                    }
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">{t("allRecommendedGrades")}</SelectItem>
                  {gradeOptions.map((g) => (
                    <SelectItem key={g.id} value={g.id}>
                      {g.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            );
          })()}
        </CardHeader>
        <CardContent>
          <div className="rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{tc("employee")}</TableHead>
                  <TableHead>{t("status")}</TableHead>
                  <TableHead>{t("colRecommendedGrade")}</TableHead>
                  <TableHead className="w-20" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {group.assessments
                  .filter((a) => {
                    if (!filterGradeId) return true;
                    return recommendations[a.id]?.grade_id === filterGradeId;
                  })
                  .map((a) => {
                    const rec = recommendations[a.id];
                    return (
                      <TableRow key={a.id}>
                        <TableCell>{a.employee_name}</TableCell>
                        <TableCell>
                          <Badge variant="outline">
                            {assessmentStatusTitle(tRef, a)}
                          </Badge>
                        </TableCell>
                        <TableCell
                          data-testid={`assessment-group-recommended-grade-${a.employee_id}`}
                        >
                          {rec?.grade_title ? (
                            <span className="flex items-center gap-2 text-sm">
                              <span className="font-medium">{rec.grade_title}</span>
                              {rec.passed ? (
                                <Badge
                                  variant="outline"
                                  className="border-green-300 text-green-700"
                                >
                                  ✓
                                </Badge>
                              ) : (
                                <Badge
                                  variant="outline"
                                  className="border-amber-300 text-amber-700"
                                >
                                  ✗
                                </Badge>
                              )}
                            </span>
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </TableCell>
                        <TableCell>
                          <Button
                            size="xs"
                            variant="ghost"
                            render={<Link href={`/assessments/${a.id}`} />}
                          >
                            {t("open")}
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* HRP-528: appears once at least one child assessment is Done; the
          component hides itself otherwise (and for non-admins). */}
      <GroupAnalytics groupId={id} />

      <CriteriaSheet
        open={criteriaOpen}
        onOpenChange={setCriteriaOpen}
        readOnly={!isGroupDraft(group)}
        initial={{
          criteria_type: group.criteria_type,
          specialization_id: group.specialization_id,
          grade_id: group.grade_id,
          competences: group.competences ?? [],
          passing_score: group.passing_score,
        }}
        onSave={saveCriteria}
      />

      <ScalePickerDialog
        open={scaleOpen}
        onOpenChange={setScaleOpen}
        currentScaleId={group.scale_id}
        onSave={saveScale}
        canManage={canManage}
        testIdPrefix="group-scale"
      />
    </div>
  );
}
