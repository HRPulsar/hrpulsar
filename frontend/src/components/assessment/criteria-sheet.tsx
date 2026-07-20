"use client";

import { useEffect, useMemo, useState } from "react";
import { Info, Pencil, X } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { ALERT_TONE } from "@/lib/badge-tones";
import { useCompetenceTree } from "@/hooks/use-competence-tree";
import type {
  AssessmentCompetence,
  Competence,
  CompetenceGroupTree,
  CriteriaType,
  CriteriaUpdate,
  GradeOption,
  GradeSpecialization,
  SkillLevel,
  SpecializationOption,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioItem } from "@/components/ui/radio";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

import { CompetenceTreeSheet } from "./competence-tree-sheet";

const ALL_GRADES_VALUE = "__all__";
const DEFAULT_PASSING_SCORE = 75;

export interface CriteriaSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initial: {
    criteria_type: CriteriaType | null;
    specialization_id: string | null;
    grade_id: string | null;
    competences: AssessmentCompetence[];
    passing_score: number | null;
  };
  /** When true, criteria are frozen — sheet is read-only and Save is hidden. */
  readOnly?: boolean;
  onSave: (data: CriteriaUpdate) => Promise<void>;
}

function flattenCompetences(groups: CompetenceGroupTree[]): Competence[] {
  const out: Competence[] = [];
  for (const g of groups) {
    out.push(...(g.competences || []));
    if (g.children?.length) out.push(...flattenCompetences(g.children));
  }
  return out;
}

function CriteriaBody({
  initial,
  readOnly,
  onClose,
  onSave,
}: {
  initial: CriteriaSheetProps["initial"];
  readOnly: boolean;
  onClose: () => void;
  onSave: CriteriaSheetProps["onSave"];
}) {
  const [type, setType] = useState<CriteriaType | "">(initial.criteria_type ?? "");
  const [specId, setSpecId] = useState<string>(initial.specialization_id ?? "");
  const [gradeId, setGradeId] = useState<string>(
    initial.specialization_id ? initial.grade_id ?? ALL_GRADES_VALUE : "",
  );
  const [competences, setCompetences] = useState<AssessmentCompetence[]>(initial.competences);
  // HRP-183 REDO: reopening the sheet must show the previously saved value.
  // Seed from initial.passing_score; if it was persisted, mark the input as
  // already-touched so the grade-default useEffect won't overwrite it.
  const [passingScore, setPassingScore] = useState<string>(
    initial.passing_score != null
      ? String(initial.passing_score)
      : String(DEFAULT_PASSING_SCORE),
  );
  const [passingScoreTouched, setPassingScoreTouched] = useState(
    initial.passing_score != null,
  );
  const [chains, setChains] = useState<GradeSpecialization[]>([]);
  // HRP-183: Individual competences doesn't produce a Recommended grade
  // chart, so the threshold is meaningless — keep the form open without
  // a passing-score block when the user picks that type.
  const passingScoreApplies =
    type === "target_position" || type === "current_positions";

  const [specs, setSpecs] = useState<SpecializationOption[]>([]);
  const [grades, setGrades] = useState<GradeOption[]>([]);
  const [skillLevels, setSkillLevels] = useState<SkillLevel[]>([]);
  const [compTypes, setCompTypes] = useState<Record<string, string>>({});

  const specItems = useMemo(
    () => specs.map((s) => ({ value: s.id, label: s.title })),
    [specs],
  );
  const gradeItems = useMemo(
    () => [
      { value: ALL_GRADES_VALUE, label: "All grades" },
      ...grades.map((g) => ({ value: g.id, label: g.title })),
    ],
    [grades],
  );
  const skillLevelItems = useMemo(
    () => skillLevels.map((sl) => ({ value: sl.id, label: sl.title })),
    [skillLevels],
  );

  const { tree: competenceTree } = useCompetenceTree();
  const compTypeMap = useMemo<Record<string, string | null>>(() => {
    const flat = flattenCompetences(competenceTree);
    return Object.fromEntries(flat.map((c) => [c.id, c.competence_type_id]));
  }, [competenceTree]);

  const [treeOpen, setTreeOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    // HRP-292: keep the saved specialization visible even if it was
    // deactivated after the criteria were set — the backend appends the
    // included id to the otherwise active-only list, so the Select can
    // render its title instead of a bare UUID.
    const savedSpecId = initial.specialization_id;
    const specsUrl = savedSpecId
      ? `/assessments/criteria/specializations?include_id=${savedSpecId}`
      : "/assessments/criteria/specializations";
    Promise.all([
      api.get<SpecializationOption[]>(specsUrl),
      api.get<SkillLevel[]>("/skill-levels"),
      api.get<{ id: string; title: string }[]>("/dictionaries/competence_type").catch(
        () => [] as { id: string; title: string }[],
      ),
    ])
      .then(([s, sl, types]) => {
        if (!alive) return;
        setSpecs(s);
        setSkillLevels([...sl].sort((a, b) => a.sort_index - b.sort_index));
        const tmap: Record<string, string> = {};
        for (const t of types) tmap[t.id] = t.title;
        setCompTypes(tmap);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [initial.specialization_id]);

  useEffect(() => {
    if (type !== "target_position" || !specId) {
      setGrades([]);
      setChains([]);
      return;
    }
    // HRP-292: inactive grades are dropped by the backend; the saved
    // grade of THIS assessment stays selectable while the user is still
    // on the originally saved specialization.
    const savedGradeId =
      specId === initial.specialization_id ? initial.grade_id : null;
    const gradesUrl = savedGradeId
      ? `/assessments/criteria/specializations/${specId}/grades?include_id=${savedGradeId}`
      : `/assessments/criteria/specializations/${specId}/grades`;
    api
      .get<GradeOption[]>(gradesUrl)
      .then(setGrades)
      .catch(() => setGrades([]));
    api
      .get<GradeSpecialization[]>(`/grade-system/specializations/${specId}`)
      .then(setChains)
      .catch(() => setChains([]));
  }, [type, specId, initial.specialization_id, initial.grade_id]);

  // Pull the per-grade default from grade_specializations whenever the user
  // hasn't manually edited the input. Switching grade re-applies the default.
  useEffect(() => {
    if (passingScoreTouched) return;
    if (type !== "target_position") {
      setPassingScore(String(DEFAULT_PASSING_SCORE));
      return;
    }
    if (gradeId && gradeId !== ALL_GRADES_VALUE && chains.length > 0) {
      const chain = chains.find((c) => c.grade_id === gradeId);
      const value = chain?.passing_score ?? DEFAULT_PASSING_SCORE;
      setPassingScore(String(value));
    } else {
      setPassingScore(String(DEFAULT_PASSING_SCORE));
    }
  }, [type, gradeId, chains, passingScoreTouched]);

  const passingScoreNumber = useMemo(() => {
    const n = Number(passingScore);
    return Number.isFinite(n) ? Math.round(n) : NaN;
  }, [passingScore]);
  const passingScoreValid =
    Number.isFinite(passingScoreNumber) &&
    passingScoreNumber >= 0 &&
    passingScoreNumber <= 100;

  const canSave = useMemo(() => {
    if (readOnly) return false;
    if (!type) return false;
    if (passingScoreApplies && !passingScoreValid) return false;
    if (type === "current_positions") return true;
    if (type === "target_position") return !!specId && !!gradeId;
    return competences.length > 0;
  }, [
    readOnly,
    type,
    specId,
    gradeId,
    competences,
    passingScoreApplies,
    passingScoreValid,
  ]);

  async function handleSave() {
    if (!canSave || !type) return;
    setSaving(true);
    try {
      const payload: CriteriaUpdate = {
        criteria_type: type as CriteriaType,
        // HRP-183: Individual competences doesn't show a passing-score
        // input and doesn't produce a recommendation, so send null and
        // let the backend store NULL (skipping recommendation).
        passing_score: passingScoreApplies ? passingScoreNumber : null,
      };
      if (type === "target_position") {
        payload.specialization_id = specId;
        payload.grade_id = gradeId === ALL_GRADES_VALUE ? null : gradeId;
      } else if (type === "competences") {
        payload.competences = competences;
      }
      await onSave(payload);
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  const groupedComps = useMemo(() => {
    const groups: Record<string, AssessmentCompetence[]> = {};
    for (const c of competences) {
      const typeId = compTypeMap[c.competence_id] || "";
      const typeTitle = compTypes[typeId] || "No type";
      if (!groups[typeTitle]) groups[typeTitle] = [];
      groups[typeTitle].push(c);
    }
    return groups;
  }, [competences, compTypeMap, compTypes]);

  return (
    <>
      <SheetContent className="max-w-lg" data-testid="criteria-sheet">
          <SheetHeader>
            <SheetTitle>Evaluation criteria</SheetTitle>
          </SheetHeader>
          <div className="rounded-md bg-accent/40 p-3 text-sm text-muted-foreground">
            <Info className="mr-2 inline-block size-4 text-primary" />
            Choose what employees will be evaluated against — a specialization
            or a hand-picked set of competences.
          </div>

          <div className="flex-1 space-y-5 overflow-y-auto">
            <RadioGroup
              value={type}
              onValueChange={(v) => setType(v as CriteriaType)}
              disabled={readOnly}
            >
              <label className="flex items-center gap-3 rounded-md border p-3" data-testid="criteria-radio-current">
                <RadioItem value="current_positions" disabled={readOnly} />
                <span className="text-sm">Employees&apos; current positions</span>
              </label>
              <label className="flex items-center gap-3 rounded-md border p-3" data-testid="criteria-radio-target">
                <RadioItem value="target_position" disabled={readOnly} />
                <span className="text-sm">Target position</span>
              </label>
              <label className="flex items-center gap-3 rounded-md border p-3" data-testid="criteria-radio-competences">
                <RadioItem value="competences" disabled={readOnly} />
                <span className="text-sm">Individual competences</span>
              </label>
            </RadioGroup>

            {readOnly && (
              <div className={`rounded-md border p-3 text-xs ${ALERT_TONE.amber}`}>
                Criteria cannot be changed after the assessment starts.
              </div>
            )}

            {type === "target_position" && (
              <Card>
                <CardContent className="space-y-3 pt-4">
                  <div className="space-y-1.5">
                    <Label>Specialization *</Label>
                    <Select
                      value={specId}
                      items={specItems}
                      onValueChange={(v) => {
                        setSpecId(v);
                        setGradeId("");
                        setPassingScoreTouched(false);
                      }}
                      disabled={readOnly}
                    >
                      <SelectTrigger className="w-full" data-testid="criteria-spec-select">
                        <SelectValue placeholder="Select" />
                      </SelectTrigger>
                      <SelectContent>
                        {specs.map((s) => (
                          <SelectItem key={s.id} value={s.id}>
                            {s.title}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <Label>Grade *</Label>
                    <Select
                      value={gradeId}
                      items={gradeItems}
                      onValueChange={(v) => {
                        setGradeId(v);
                        setPassingScoreTouched(false);
                      }}
                      disabled={!specId || readOnly}
                    >
                      <SelectTrigger className="w-full" data-testid="criteria-grade-select">
                        <SelectValue placeholder="Select" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={ALL_GRADES_VALUE}>All grades</SelectItem>
                        {grades.map((g) => (
                          <SelectItem key={g.id} value={g.id}>
                            {g.title}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="border-t pt-3">
                    <PassingScoreField
                      value={passingScore}
                      onChange={(v) => {
                        setPassingScore(v);
                        setPassingScoreTouched(true);
                      }}
                      disabled={readOnly}
                      invalid={!passingScoreValid}
                    />
                  </div>

                  {!readOnly && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setSpecId("");
                        setGradeId("");
                        setPassingScoreTouched(false);
                      }}
                    >
                      <X className="mr-1 size-3.5" /> Clear
                    </Button>
                  )}
                </CardContent>
              </Card>
            )}

            {type === "current_positions" && (
              <Card>
                <CardContent className="pt-4">
                  <PassingScoreField
                    value={passingScore}
                    onChange={(v) => {
                      setPassingScore(v);
                      setPassingScoreTouched(true);
                    }}
                    disabled={readOnly}
                    invalid={!passingScoreValid}
                  />
                </CardContent>
              </Card>
            )}

            {type === "competences" && (
              <div className="space-y-3">
                {competences.length === 0 ? (
                  <Card>
                    <CardContent className="flex flex-col items-center gap-3 py-8 text-center">
                      <p className="text-sm text-muted-foreground">
                        Select the competences this assessment evaluates
                      </p>
                      <Button onClick={() => setTreeOpen(true)} data-testid="criteria-pick-competences">
                        <Pencil className="mr-1 size-3.5" /> Select
                      </Button>
                    </CardContent>
                  </Card>
                ) : (
                  <>
                    <p className="rounded-md bg-accent/40 p-2 text-xs text-muted-foreground">
                      <Info className="mr-1 inline-block size-3 text-primary" />
                      Each skill level includes the indicators of all preceding levels
                    </p>
                    {Object.entries(groupedComps).map(([typeTitle, items]) => (
                      <Card key={typeTitle}>
                        <CardContent className="space-y-2 pt-4">
                          <div className="flex items-center justify-between text-sm">
                            <span className="font-medium">{typeTitle}</span>
                            <span className="text-xs text-muted-foreground">Skill level</span>
                          </div>
                          {items.map((item) => {
                            return (
                              <div
                                key={item.competence_id}
                                className="flex items-center gap-2 rounded-md border px-3 py-2"
                                data-testid={`criteria-comp-${item.competence_id}`}
                              >
                                <span className="flex-1 truncate text-sm">
                                  {item.competence_title}
                                </span>
                                <Select
                                  value={item.skill_level_id ?? ""}
                                  // Base UI Select.Value renders the raw value
                                  // (the UUID) unless `items` is supplied —
                                  // pass the [value, label] map so the trigger
                                  // shows "Basic" instead of a UUID.
                                  items={skillLevelItems}
                                  onValueChange={(val) => {
                                    const picked = skillLevels.find((sl) => sl.id === val);
                                    setCompetences((prev) =>
                                      prev.map((c) =>
                                        c.competence_id === item.competence_id
                                          ? {
                                              ...c,
                                              skill_level_id: val,
                                              skill_level_title: picked?.title ?? null,
                                            }
                                          : c,
                                      ),
                                    );
                                  }}
                                >
                                  <SelectTrigger className="w-32">
                                    <SelectValue placeholder="—" />
                                  </SelectTrigger>
                                  <SelectContent>
                                    {skillLevels.map((sl) => (
                                      <SelectItem key={sl.id} value={sl.id}>
                                        {sl.title}
                                      </SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>
                                <Button
                                  variant="ghost"
                                  size="icon-sm"
                                  onClick={() =>
                                    setCompetences((prev) =>
                                      prev.filter((c) => c.competence_id !== item.competence_id),
                                    )
                                  }
                                >
                                  <X className="size-3.5" />
                                </Button>
                              </div>
                            );
                          })}
                        </CardContent>
                      </Card>
                    ))}
                    <div className="flex justify-between">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setCompetences([])}
                      >
                        <X className="mr-1 size-3.5" /> Remove all
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setTreeOpen(true)}
                      >
                        <Pencil className="mr-1 size-3.5" /> Edit
                      </Button>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>

        <SheetFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            {readOnly ? "Close" : "Cancel"}
          </Button>
          {!readOnly && (
            <Button
              onClick={handleSave}
              disabled={!canSave || saving}
              data-testid="criteria-save"
            >
              {saving ? "Saving…" : "Save"}
            </Button>
          )}
        </SheetFooter>
      </SheetContent>

      <CompetenceTreeSheet
        open={treeOpen}
        onOpenChange={setTreeOpen}
        initialIds={competences.map((c) => c.competence_id)}
        onSave={(picked) => {
          const map = new Map(competences.map((c) => [c.competence_id, c]));
          setCompetences(
            picked.map(
              ({ id, title }) =>
                map.get(id) ?? {
                  competence_id: id,
                  competence_title: title,
                  skill_level_id: null,
                  skill_level_title: null,
                },
            ),
          );
        }}
      />
    </>
  );
}

export function CriteriaSheet({
  open,
  onOpenChange,
  initial,
  readOnly = false,
  onSave,
}: CriteriaSheetProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      {open && (
        <CriteriaBody
          initial={initial}
          readOnly={readOnly}
          onClose={() => onOpenChange(false)}
          onSave={onSave}
        />
      )}
    </Sheet>
  );
}

interface PassingScoreFieldProps {
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  invalid: boolean;
}

// HRP-183: only used for target_position and current_positions; the (i)
// tooltip and the "How match % is calculated" toggle were dropped per the
// REDO comment — both were noise next to the input.
function PassingScoreField({
  value,
  onChange,
  disabled,
  invalid,
}: PassingScoreFieldProps) {
  return (
    <div className="space-y-2">
      <Label htmlFor="criteria-passing-score">
        Passing score for recommended grade (%)
      </Label>
      <div className="flex items-center gap-3">
        <Input
          id="criteria-passing-score"
          data-testid="assessment-criteria-passing-score-input"
          type="number"
          inputMode="numeric"
          min={0}
          max={100}
          step={1}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          aria-invalid={invalid || undefined}
          className="w-24"
        />
        <span className="text-xs text-muted-foreground">step 1%, range 0–100</span>
      </div>
      {invalid && (
        <p className="text-xs text-destructive">
          Enter a whole number between 0 and 100.
        </p>
      )}
    </div>
  );
}
