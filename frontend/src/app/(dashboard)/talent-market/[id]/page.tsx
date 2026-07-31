"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { BADGE_COLOR } from "@/lib/badge-tones";
import type {
  Competence,
  CompetenceGroupTree,
  DictionaryItem,
  Division,
  SkillLevel,
  TalentCardDetail,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { DatePicker } from "@/components/ui/date-picker";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ConfirmDialog } from "@/components/confirm-dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";
import { formatDate } from "@/lib/date-format";
import {
  ArrowLeft,
  Check,
  CheckCircle2,
  ChevronRight,
  Globe,
  Pencil,
  RefreshCw,
  UserPlus,
  X,
  XCircle,
} from "lucide-react";
import { Textarea } from "@/components/ui/textarea";
import {
  RequiredCompetencesBlock,
  RequiredSpecializationsBlock,
} from "@/components/talent-market/requirement-blocks";
import { MatchDrawer } from "@/components/talent-market/match-drawer";
import { EmployeeSummaryLine } from "@/components/employee/employee-summary-line";
import { inlineEditKeys, useInlineEdit } from "@/hooks/use-inline-edit";
import { usePermissions } from "@/hooks/use-permissions";

const statusColors: Record<string, string> = {
  draft: BADGE_COLOR.neutral,
  published: BADGE_COLOR.blue,
  // Keep `closed` for legacy rows; new code paths emit `completed`.
  closed: BADGE_COLOR.green,
  completed: BADGE_COLOR.green,
  cancelled: BADGE_COLOR.red,
};

// HRP-148: capitalised labels per spec (lowercase codes come from the API).
// HRP-476: the map holds i18n keys in the `talentMarket` namespace.
const STATUS_KEYS: Record<string, string> = {
  draft: "statusDraft",
  published: "statusPublished",
  completed: "statusCompleted",
  closed: "statusCompleted",
  cancelled: "statusCancelled",
};

/** Translated status label with a raw-code fallback for unknown values. */
function statusLabel(t: (key: string) => string, status: string): string {
  const key = STATUS_KEYS[status];
  return key ? t(key) : status;
}

const TERMINAL_STATUSES = new Set(["completed", "closed", "cancelled"]);

const typeColors: Record<string, string> = {
  vacancy: BADGE_COLOR.blue,
  talent: BADGE_COLOR.purple,
  project: BADGE_COLOR.cyan,
};


// HRP-167: red-highlight the dates row when End date is in the past on
// active cards (Draft / Published). Terminal cards keep the neutral
// palette.
function isOverdue(card: TalentCardDetail): boolean {
  if (!card.end_date) return false;
  if (TERMINAL_STATUSES.has(card.status)) return false;
  const today = new Date();
  const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  return card.end_date.slice(0, 10) < todayIso;
}

// HRP-92 REDO: terminal cards show "Completed: yyyy-mm-dd" /
// "Cancelled: yyyy-mm-dd" instead of the legacy "Closed:" label,
// matching the Assessments section. Active cards (Draft / Published)
// still render the date range.
function formatCardTermLabel(
  t: (key: string, values?: Record<string, string>) => string,
  card: TalentCardDetail,
): string {
  if (card.status === "completed" || card.status === "closed") {
    const when = card.completed_at ?? card.closed_at;
    if (when) {
      return t("termCompleted", { date: formatDate(when.slice(0, 10)) });
    }
  }
  if (card.status === "cancelled") {
    const when = card.cancelled_at ?? card.closed_at;
    if (when) {
      return t("termCancelled", { date: formatDate(when.slice(0, 10)) });
    }
  }
  if (card.end_date) {
    return t("termRange", {
      start: formatDate(card.start_date),
      end: formatDate(card.end_date),
    });
  }
  return t("termSince", { date: formatDate(card.start_date) });
}

// HRP-214: Candidates table now renders matched / not_matched / appointed
// directly from the persisted status. Legacy values (nominated / pending
// / rejected / responded) are kept in the map so historic rows still get
// a readable badge before the migration backfills them.
const candidateStatusColors: Record<string, string> = {
  matched: BADGE_COLOR.green,
  not_matched: BADGE_COLOR.neutral,
  appointed: BADGE_COLOR.green,
  nominated: BADGE_COLOR.yellow,
  pending: BADGE_COLOR.yellow,
  rejected: BADGE_COLOR.red,
  responded: BADGE_COLOR.blue,
};

// HRP-476: code → key in the `talentMarket` namespace. Legacy statuses
// have no key and fall through to the raw code, as before.
const CANDIDATE_STATUS_KEYS: Record<string, string> = {
  matched: "candidateStatusMatched",
  not_matched: "candidateStatusNotMatched",
  appointed: "candidateStatusAppointed",
};

function candidateStatusLabel(
  t: (key: string) => string,
  value: string,
): string {
  const key = CANDIDATE_STATUS_KEYS[value];
  return key ? t(key) : value;
}

// HRP-95 / HRP-173: picker row returned by GET /talent-market/{id}/candidate-pool.
// `status` is "matched" / "not_matched" / "appointed"; `basis` tells the
// UI whether the score came from competence assessments or work-experience
// years (or "none" — the card has no requirements yet). The HRP-173
// fields below drive the colour rules (green / orange / red) on the
// Match cell. HRP-214: `appointed` is only surfaced in Change mode for
// already-attached candidates and the picker locks the row's checkbox.
type CandidatePoolItem = {
  employee_id: string;
  name: string;
  status: "matched" | "not_matched" | "appointed";
  match_score: number;
  basis: "competence" | "experience" | "none";
  comp_match: number | null;
  comp_qualifies: boolean;
  exp_months: number | null;
  exp_qualifies: boolean;
  has_comp_requirement: boolean;
  has_spec_requirement: boolean;
  exp_via_current_position?: boolean;
  // HRP-258: feed EmployeeSummaryLine on the picker rows.
  position_title?: string | null;
  employee_status?: string | null;
};

// HRP-476: the wording lives in the `talentMarket` i18n namespace, so the
// helpers below take the translator as a parameter.
function formatExperienceMonths(
  t: (key: string, values?: Record<string, number>) => string,
  total: number | null,
): string {
  if (total === null) return t("matchNoExperience");
  if (total <= 0) return t("expLessThanMonth");
  const years = Math.floor(total / 12);
  const months = total % 12;
  const yearPart = years ? t("expYearsShort", { count: years }) : "";
  const monthPart = months ? t("expMonthsShort", { count: months }) : "";
  return (
    `${yearPart}${yearPart && monthPart ? " " : ""}${monthPart}` ||
    t("expLessThanMonth")
  );
}

// HRP-242: short label for the "last match" stamp in the Candidates
// block header. Returns null for empty timestamps so the caller can
// hide the row instead of rendering a sentinel.
const MONTH_SHORT_KEYS = [
  "monthShortJan",
  "monthShortFeb",
  "monthShortMar",
  "monthShortApr",
  "monthShortMay",
  "monthShortJun",
  "monthShortJul",
  "monthShortAug",
  "monthShortSep",
  "monthShortOct",
  "monthShortNov",
  "monthShortDec",
];

function formatLastMatched(
  t: (key: string, values?: Record<string, string>) => string,
  iso: string | null | undefined,
): {
  short: string;
  tooltip: string;
} | null {
  if (!iso) return null;
  const ts = new Date(iso);
  if (Number.isNaN(ts.getTime())) return null;
  const pad = (n: number) => String(n).padStart(2, "0");
  const tooltip =
    `${ts.getFullYear()}-${pad(ts.getMonth() + 1)}-${pad(ts.getDate())} ` +
    `${pad(ts.getHours())}:${pad(ts.getMinutes())}`;
  const today = new Date();
  const startOfToday = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate(),
  );
  const startOfTs = new Date(ts.getFullYear(), ts.getMonth(), ts.getDate());
  const dayDiff = Math.round(
    (startOfToday.getTime() - startOfTs.getTime()) / 86_400_000,
  );
  if (dayDiff <= 0) return { short: t("lastMatchedToday"), tooltip };
  if (dayDiff === 1) return { short: t("lastMatchedYesterday"), tooltip };
  const month = t(MONTH_SHORT_KEYS[ts.getMonth()]);
  const day = String(ts.getDate());
  if (ts.getFullYear() === today.getFullYear()) {
    return { short: t("lastMatchedMonthDay", { month, day }), tooltip };
  }
  return {
    short: t("lastMatchedMonthDayYear", {
      month,
      day,
      year: String(ts.getFullYear()),
    }),
    tooltip,
  };
}

// HRP-173: stacked Match cell. Renders a Competencies row (colour by
// qualifies + comp_match presence) and, when the card carries Required
// specializations, an Experience row below it.
// HRP-172 redo: the chips are no longer the click target — only the
// trailing chevron opens the breakdown drawer, and it shows in its
// "active" hover-state styling whenever the drawer is open for this row.
function MatchCell({
  item,
  onOpen,
  testIdPrefix,
  isOpen,
  hideTrigger = false,
}: {
  item: {
    comp_match: number | null;
    comp_qualifies: boolean;
    exp_months: number | null;
    exp_qualifies: boolean;
    has_comp_requirement: boolean;
    has_spec_requirement: boolean;
    // HRP-210: greyed "has experience" chip when only the current
    // Position lines up with one of the Required specializations.
    exp_via_current_position?: boolean;
  };
  onOpen: () => void;
  testIdPrefix: string;
  isOpen?: boolean;
  // HRP-209: Employee viewers can only open the drawer for their own
  // candidate row, so other rows render the chips without the chevron.
  hideTrigger?: boolean;
}) {
  const t = useTranslations("talentMarket");
  const hasComp = item.has_comp_requirement;
  const hasSpec = item.has_spec_requirement;
  // HRP-173 redo: each chip is coloured by its own rule — no cross-rule
  // shading between competencies and experience.
  //   Competency chip:
  //     %  >= threshold  → green
  //     %  <  threshold  → red
  //     null (no scoring) → muted "no assessment" / "no assessments" copy
  //   Experience chip (only when the card has Required specializations):
  //     >= min experience (or no min set) → green
  //     <  min experience                  → red
  //     no tenure on the matching specs    → muted "no experience"
  let compChip: string = BADGE_COLOR.neutral;
  let compText = "—";
  if (hasComp) {
    if (item.comp_match === null) {
      compChip = BADGE_COLOR.neutral;
      // HRP-173 redo case 2.2: when the card has no Required spec the
      // unscored fallback is "no assessments" (not "no experience").
      compText = hasSpec
        ? t("matchNoAssessment")
        : t("matchNoAssessments");
    } else {
      compChip = item.comp_qualifies ? BADGE_COLOR.green : BADGE_COLOR.red;
      compText = `${item.comp_match}%`;
    }
  }
  let expChip: string = BADGE_COLOR.neutral;
  let expText = t("matchNoExperience");
  if (hasSpec) {
    if (item.exp_months === null) {
      // HRP-210: no WorkExperience tenure to show — fall back to the
      // employee's current Position if it lines up with any Required
      // spec ("has experience" greyed). Otherwise stays "no experience".
      expChip = BADGE_COLOR.neutral;
      expText = item.exp_via_current_position
        ? t("matchHasExperience")
        : t("matchNoExperience");
    } else {
      expText = formatExperienceMonths(t, item.exp_months);
      expChip = item.exp_qualifies ? BADGE_COLOR.green : BADGE_COLOR.red;
    }
  }
  return (
    <div
      className="flex items-center justify-end gap-2"
      data-testid={`${testIdPrefix}-match`}
    >
      <div className="flex flex-col items-end gap-1 text-right tabular-nums">
        <span
          className={`rounded px-2 py-0.5 text-xs ${compChip}`}
          data-testid={`${testIdPrefix}-match-competence`}
        >
          {compText}
        </span>
        {hasSpec && (
          <span
            className={`rounded px-2 py-0.5 text-xs ${expChip}`}
            data-testid={`${testIdPrefix}-match-experience`}
          >
            {expText}
          </span>
        )}
      </div>
      {!hideTrigger && (
        <button
          type="button"
          onClick={onOpen}
          aria-label={t("openMatchBreakdown")}
          aria-pressed={isOpen ? true : undefined}
          // HRP-172 redo item 2: when the drawer is open for this row the
          // chevron stays in its hover/active styling so the operator can
          // tell at a glance which candidate the open Sheet belongs to.
          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
            isOpen ? "bg-accent text-foreground" : ""
          }`}
          data-testid={`${testIdPrefix}-match-trigger`}
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}

export default function TalentCardDetailPage() {
  const t = useTranslations("talentMarket");
  const tc = useTranslations("common");
  const { id } = useParams<{ id: string }>();
  const [card, setCard] = useState<TalentCardDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [divisionName, setDivisionName] = useState<string | null>(null);
  // HRP-209: role gates the Match pencil, Appoint button, picker
  // affordances and drawer arrows for the Employee role. The viewer
  // can manage when they're admin / manager (full read+write); plain
  // employees only see the Candidates table without write controls.
  const { canManage } = usePermissions();

  // Dictionaries used by both Requirement blocks. Loaded once on mount.
  const [specializations, setSpecializations] = useState<DictionaryItem[]>([]);
  const [grades, setGrades] = useState<DictionaryItem[]>([]);
  const [skillLevels, setSkillLevels] = useState<SkillLevel[]>([]);
  const [tree, setTree] = useState<CompetenceGroupTree[]>([]);

  // HRP-95: Add/Change candidate picker dialog. `pool` holds the rankable
  // employee list returned by the backend (sorted by match desc);
  // `selectedIds` tracks the checkbox state. `pickerMode` switches between
  // "add" (empty selection) and "change" (pre-checks attached candidates,
  // diffs on Save). `initialIds` snapshots the pre-existing set so Save can
  // compute additions/removals.
  const [candOpen, setCandOpen] = useState(false);
  const [pickerMode, setPickerMode] = useState<"add" | "change">("add");
  const [pool, setPool] = useState<CandidatePoolItem[]>([]);
  const [poolLoading, setPoolLoading] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [initialIds, setInitialIds] = useState<Set<string>>(new Set());
  const [candidateFilter, setCandidateFilter] = useState("");

  const [saving, setSaving] = useState(false);

  // HRP-172: match breakdown drawer state. Opened from the Match cell in
  // the Candidates table and the Add / Change picker rows.
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerEmployeeId, setDrawerEmployeeId] = useState<string | null>(null);
  const [drawerEmployeeName, setDrawerEmployeeName] = useState<string | null>(
    null,
  );

  // HRP-215: confirm before running the appointment so a stray click on
  // the row's Appoint button doesn't pin an employee.
  const [appointTarget, setAppointTarget] = useState<{
    candidateId: string;
    employeeName: string | null;
  } | null>(null);

  // HRP-213: confirm React before sending it — the employee should
  // notice the click; once the reaction is in there's no undo
  // affordance on the UI.
  const [reactConfirmOpen, setReactConfirmOpen] = useState(false);

  function openMatchDrawer(employeeId: string, name?: string | null) {
    setDrawerEmployeeId(employeeId);
    setDrawerEmployeeName(name ?? null);
    setDrawerOpen(true);
  }

  // HRP-148: inline-edit slots for Title / Description / Dates on the
  // card detail page. Mirrors the assessment-detail UX (HRP-110) so the
  // affordance is consistent across non-terminal entity pages. Each
  // field saves via PUT /talent-market/{id} with only its delta.
  const titleEdit = useInlineEdit<string>(() => "");
  const descEdit = useInlineEdit<string>(() => "");
  const datesEdit = useInlineEdit<{ start: string; end: string }>(() => ({
    start: "",
    end: "",
  }));
  // HRP-179: card-level Match% inline edit. Draft only — the backend
  // enforces a publish-lock on match_percent (HRP-128), so the affordance
  // is hidden once the card flips out of Draft.
  const matchEdit = useInlineEdit<string>(() => "");

  const load = useCallback(async () => {
    try {
      const detail = await api.get<TalentCardDetail>(`/talent-market/${id}`);
      setCard(detail);
      if (detail.division_id) {
        try {
          const div = await api.get<Division>(`/divisions/${detail.division_id}`);
          setDivisionName(div.name);
        } catch {
          setDivisionName(null);
        }
      } else {
        setDivisionName(null);
      }
    } catch {
      toast.error(t("toastLoadCardFailed"));
    } finally {
      setLoading(false);
    }
  }, [id, t]);

  useEffect(() => {
    load();
  }, [load]);

  // One-off dictionaries — used by Required Spec / Required Comp blocks.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [specs, gradesList, levels, treeData] = await Promise.all([
          api.get<DictionaryItem[]>("/dictionaries/specialization").catch(
            () => [],
          ),
          api.get<DictionaryItem[]>("/dictionaries/grade").catch(() => []),
          api.get<SkillLevel[]>("/skill-levels").catch(() => []),
          api.get<CompetenceGroupTree[]>("/competence-tree").catch(() => []),
        ]);
        if (cancelled) return;
        setSpecializations(specs);
        setGrades(gradesList);
        setSkillLevels(levels);
        setTree(treeData);
      } catch {
        if (!cancelled) {
          // Empty arrays are fine — UI shows a "set this up first" hint.
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const competenceById = useMemo(() => {
    const map = new Map<string, Competence>();
    function visit(g: CompetenceGroupTree) {
      for (const c of g.competences ?? []) map.set(c.id, c);
      for (const ch of g.children ?? []) visit(ch);
    }
    for (const g of tree) visit(g);
    return map;
  }, [tree]);

  async function publish() {
    setSaving(true);
    try {
      await api.post(`/talent-market/${id}/publish`, {});
      toast.success(t("toastCardPublished"));
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastPublishFailed"));
    } finally {
      setSaving(false);
    }
  }

  // HRP-150: terminal transitions from Published.
  async function completeCard() {
    setSaving(true);
    try {
      await api.post(`/talent-market/${id}/complete`, {});
      toast.success(t("toastCardCompleted"));
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastCompleteFailed"));
    } finally {
      setSaving(false);
    }
  }

  async function cancelCard() {
    setSaving(true);
    try {
      await api.post(`/talent-market/${id}/cancel`, {});
      toast.success(t("toastCardCancelled"));
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastCancelFailed"));
    } finally {
      setSaving(false);
    }
  }

  // HRP-148: shared save helper for the inline-edit fields. The card
  // service's update_card already merges partial payloads, so we only
  // ship the delta.
  async function saveField(
    patch: Record<string, unknown>,
    onSuccess: () => void,
  ) {
    setSaving(true);
    try {
      await api.put(`/talent-market/${id}`, patch);
      toast.success(t("toastSaved"));
      onSuccess();
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastSaveFailed"));
    } finally {
      setSaving(false);
    }
  }

  async function saveTitle() {
    const next = titleEdit.draft.trim();
    if (!next) {
      toast.error(t("toastTitleRequired"));
      return;
    }
    await saveField({ title: next }, () => titleEdit.close());
  }

  async function saveDescription() {
    await saveField(
      { description: descEdit.draft.trim() || null },
      () => descEdit.close(),
    );
  }

  async function saveMatch() {
    // HRP-179: card-level Match% accepts integers in [50, 100] per the
    // backend's pydantic gate. Reject anything else client-side so the
    // user gets a clear toast instead of a 422.
    const raw = matchEdit.draft.trim();
    const next = Number(raw);
    if (!raw || !Number.isInteger(next) || next < 50 || next > 100) {
      toast.error(t("toastMatchRangeInline"));
      return;
    }
    await saveField({ match_percent: next }, () => matchEdit.close());
  }

  async function saveDates() {
    const { start, end } = datesEdit.draft;
    if (!start) {
      toast.error(t("toastStartDateRequired"));
      return;
    }
    if (end && end < start) {
      toast.error(t("toastEndDateBeforeStart"));
      return;
    }
    await saveField(
      { start_date: start, end_date: end || null },
      () => datesEdit.close(),
    );
  }

  // HRP-95: load the rankable pool when the picker opens. Re-fetched each
  // time the dialog is opened so a candidate added in a parallel tab can't
  // double-list. Change mode passes `include_attached=true` so already-
  // linked employees appear in the list (pre-checked).
  const loadPool = useCallback(
    async (includeAttached: boolean) => {
      setPoolLoading(true);
      try {
        const qs = includeAttached ? "?include_attached=true" : "";
        const res = await api.get<{ items: CandidatePoolItem[] }>(
          `/talent-market/${id}/candidate-pool${qs}`,
        );
        setPool(res.items);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t("toastLoadFailed"));
      } finally {
        setPoolLoading(false);
      }
    },
    [id, t],
  );

  function openCandidatePicker() {
    // HRP-95: empty candidate list → Add; otherwise the picker opens in
    // Change mode with current candidates pre-checked. The picker
    // re-fetches the pool either way (server filters out already-linked
    // for add-only — in change mode we need to *see* them, so the pool
    // call includes attached rows).
    const isChange = card !== null && card.candidates.length > 0;
    const attached = new Set<string>(
      card?.candidates.map((c) => c.employee_id) ?? [],
    );
    setPickerMode(isChange ? "change" : "add");
    setInitialIds(attached);
    setSelectedIds(new Set(attached));
    setCandidateFilter("");
    setCandOpen(true);
    loadPool(isChange);
  }

  function toggleCandidate(employeeId: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(employeeId)) next.delete(employeeId);
      else next.add(employeeId);
      return next;
    });
  }

  async function savePicker() {
    // HRP-95: shared submit for Add + Change. Add bulk-creates the chosen
    // employees; Change diffs against the initial set, bulk-adding new
    // picks and DELETEing each unchecked row.
    setSaving(true);
    try {
      const added: string[] = [];
      const removed: string[] = [];
      for (const emp of selectedIds) {
        if (!initialIds.has(emp)) added.push(emp);
      }
      for (const emp of initialIds) {
        if (!selectedIds.has(emp)) removed.push(emp);
      }
      if (pickerMode === "add" && added.length === 0) return;
      if (added.length > 0) {
        await api.post(`/talent-market/${id}/candidates/bulk`, {
          employee_ids: added,
        });
      }
      for (const emp of removed) {
        await api.delete(`/talent-market/${id}/candidates/${emp}`);
      }
      if (pickerMode === "add") {
        toast.success(t("toastCandidatesAdded", { count: added.length }));
      } else {
        toast.success(t("toastCandidatesUpdated"));
      }
      setCandOpen(false);
      setSelectedIds(new Set());
      setInitialIds(new Set());
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastFailed"));
    } finally {
      setSaving(false);
    }
  }

  async function appointCandidate(candidateId: string) {
    setSaving(true);
    try {
      await api.post(`/talent-market/${id}/candidates/${candidateId}/appoint`, {});
      toast.success(t("toastCandidateAppointed"));
      setAppointTarget(null);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastFailed"));
    } finally {
      setSaving(false);
    }
  }

  // HRP-242: rerun the Candidates auto-pool from the block header. Only
  // wired up for non-terminal cards + managing roles; the icon is hidden
  // otherwise.
  async function refreshMatch() {
    setSaving(true);
    try {
      await api.post(`/talent-market/${id}/recompute`, {});
      toast.success(t("toastCandidatesRefreshed"));
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastRefreshFailed"));
    } finally {
      setSaving(false);
    }
  }

  // HRP-213: employee reaction action — confirmation lives in a
  // ConfirmDialog; this sends the POST and reloads on success.
  async function sendReaction() {
    setSaving(true);
    try {
      await api.post(`/talent-market/${id}/react`, {});
      toast.success(t("toastReactionSent"));
      setReactConfirmOpen(false);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastReactFailed"));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <div className="flex items-center justify-center py-12 text-muted-foreground">{tc("loading")}</div>;
  }

  if (!card) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" render={<Link href="/talent-market" />}>
          <ArrowLeft className="mr-1 h-4 w-4" />
          {t("backToTalentMarket")}
        </Button>
        <div className="py-12 text-center text-muted-foreground">{t("cardNotFound")}</div>
      </div>
    );
  }

  // HRP-148: terminal cards block inline edits (Pencil hidden + the
  // existing publish-lock on Required blocks).
  const isTerminal = TERMINAL_STATUSES.has(card.status);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon-sm" render={<Link href="/talent-market" />}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          {/* HRP-148: inline-edit Title (pencil hidden when terminal). */}
          {titleEdit.editing ? (
            <div className="flex items-center gap-2">
              <Input
                value={titleEdit.draft}
                onChange={(e) => titleEdit.setDraft(e.target.value)}
                onKeyDown={inlineEditKeys({
                  onCommit: saveTitle,
                  onCancel: titleEdit.cancel,
                  disabled: saving,
                })}
                className="h-9 max-w-md text-base"
                autoFocus
                disabled={saving}
                maxLength={100}
                data-testid="talent-market-input-edit-title"
              />
              <Button
                size="icon-sm"
                onClick={saveTitle}
                disabled={saving}
                data-testid="talent-market-btn-save-title"
              >
                <Check className="h-4 w-4" />
              </Button>
              <Button
                size="icon-sm"
                variant="ghost"
                onClick={titleEdit.cancel}
                disabled={saving}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          ) : (
            <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
              <span>{card.title}</span>
              {!isTerminal && canManage && (
                <Button
                  size="icon-sm"
                  variant="ghost"
                  onClick={() => titleEdit.start(card.title)}
                  data-testid="talent-market-btn-edit-title"
                >
                  <Pencil className="h-4 w-4" />
                </Button>
              )}
            </h1>
          )}
          {descEdit.editing ? (
            <div className="mt-2 flex items-start gap-2">
              <Textarea
                value={descEdit.draft}
                onChange={(e) => descEdit.setDraft(e.target.value)}
                onKeyDown={inlineEditKeys({
                  onCommit: saveDescription,
                  onCancel: descEdit.cancel,
                  disabled: saving,
                })}
                className="max-w-md text-sm"
                autoFocus
                disabled={saving}
                maxLength={250}
                rows={3}
                data-testid="talent-market-input-edit-description"
              />
              <div className="flex flex-col gap-1">
                <Button
                  size="icon-sm"
                  onClick={saveDescription}
                  disabled={saving}
                  data-testid="talent-market-btn-save-description"
                >
                  <Check className="h-4 w-4" />
                </Button>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  onClick={descEdit.cancel}
                  disabled={saving}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ) : (
            <p className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
              {card.description ? (
                <span>{card.description}</span>
              ) : (
                // HRP-148 REDO: active cards get the italic "No description
                // yet" hint paired with the pencil affordance; terminal
                // cards just render a plain "No description" line — no
                // call-to-action since editing is closed off.
                <span
                  className={isTerminal ? undefined : "italic"}
                  data-testid="talent-market-description-empty"
                >
                  {isTerminal ? t("noDescription") : t("noDescriptionYet")}
                </span>
              )}
              {!isTerminal && canManage && (
                <Button
                  size="icon-sm"
                  variant="ghost"
                  onClick={() =>
                    descEdit.start(card.description ?? "")
                  }
                  data-testid="talent-market-btn-edit-description"
                >
                  <Pencil className="h-4 w-4" />
                </Button>
              )}
            </p>
          )}
        </div>
        <Badge variant="secondary" className={typeColors[card.card_type] || ""}>{card.card_type}</Badge>
        <Badge variant="secondary" className={statusColors[card.status] || ""}>
          {statusLabel(t, card.status)}
        </Badge>
      </div>

      {/* Info */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("detailsTitle")}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-3">
            <div>
              <p className="text-muted-foreground">{t("fieldType")}</p>
              <Badge variant="secondary" className={typeColors[card.card_type] || ""}>{card.card_type}</Badge>
            </div>
            <div>
              <p className="text-muted-foreground">{t("fieldStatus")}</p>
              <Badge variant="secondary" className={statusColors[card.status] || ""}>
                {statusLabel(t, card.status)}
              </Badge>
            </div>
            {divisionName && (
              <div>
                <p className="text-muted-foreground">{t("fieldDivision")}</p>
                <p className="font-medium" data-testid="talent-market-detail-division">{divisionName}</p>
              </div>
            )}
            <div>
              <p className="text-muted-foreground">{t("fieldCreated")}</p>
              <p className="font-medium">{formatDate(card.created_at)}</p>
            </div>
            {/* HRP-178: terminal cards (Completed / Cancelled) drop the
              Dates row from Details — the status-specific date below
              already carries the timestamp. Active cards (Draft /
              Published) keep the row + inline pencil edit. */}
            {!isTerminal && (
            <div>
              <p className="text-muted-foreground">{t("fieldDates")}</p>
              {datesEdit.editing ? (
                <div className="mt-1 flex flex-col gap-2 sm:flex-row sm:items-center">
                  {/* HRP-335: shared DatePicker (HRP-152). */}
                  <DatePicker
                    value={datesEdit.draft.start}
                    onChange={(value) =>
                      datesEdit.setDraft({
                        ...datesEdit.draft,
                        start: value,
                      })
                    }
                    className="w-44"
                    inputClassName="h-8 text-sm"
                    disabled={saving}
                    data-testid="talent-market-input-edit-start-date"
                  />
                  <span className="text-muted-foreground">–</span>
                  <DatePicker
                    value={datesEdit.draft.end}
                    onChange={(value) =>
                      datesEdit.setDraft({
                        ...datesEdit.draft,
                        end: value,
                      })
                    }
                    className="w-44"
                    inputClassName="h-8 text-sm"
                    disabled={saving}
                    min={datesEdit.draft.start}
                    data-testid="talent-market-input-edit-end-date"
                  />
                  <div className="flex gap-1">
                    <Button
                      size="icon-sm"
                      onClick={saveDates}
                      disabled={saving}
                      data-testid="talent-market-btn-save-dates"
                    >
                      <Check className="h-4 w-4" />
                    </Button>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      onClick={datesEdit.cancel}
                      disabled={saving}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ) : (
                <p
                  className={`flex items-center gap-2 font-medium ${
                    isOverdue(card) ? "text-destructive" : ""
                  }`}
                  data-testid="talent-market-detail-dates"
                >
                  <span>{formatCardTermLabel(t, card)}</span>
                  {!isTerminal && canManage && (
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      onClick={() =>
                        datesEdit.start({
                          start: card.start_date?.slice(0, 10) ?? "",
                          end: card.end_date?.slice(0, 10) ?? "",
                        })
                      }
                      data-testid="talent-market-btn-edit-dates"
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                  )}
                </p>
              )}
            </div>
            )}
            <div>
              {/* HRP-128 + HRP-179: card-level Match% — inline-editable
                on Draft only (the backend rejects edits past Publish via
                a 409). Non-draft cards just render the value. */}
              <p className="text-muted-foreground">{t("fieldMatch")}</p>
              {matchEdit.editing ? (
                <div className="mt-1 flex items-center gap-2">
                  <Input
                    type="number"
                    min={50}
                    max={100}
                    value={matchEdit.draft}
                    onChange={(e) => matchEdit.setDraft(e.target.value)}
                    onKeyDown={inlineEditKeys({
                      onCommit: saveMatch,
                      onCancel: matchEdit.cancel,
                      disabled: saving,
                    })}
                    className="h-8 w-20 text-sm"
                    autoFocus
                    disabled={saving}
                    data-testid="talent-market-input-edit-match"
                  />
                  <span className="text-sm text-muted-foreground">%</span>
                  <Button
                    size="icon-sm"
                    onClick={saveMatch}
                    disabled={saving}
                    data-testid="talent-market-btn-save-match"
                  >
                    <Check className="h-4 w-4" />
                  </Button>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    onClick={matchEdit.cancel}
                    disabled={saving}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              ) : (
                <p
                  className="flex items-center gap-2 font-medium"
                  data-testid="talent-market-detail-match"
                >
                  <span>{card.match_percent}%</span>
                  {/* HRP-209: Match% pencil hidden for Employee — the
                      backend already rejects edits via require_role,
                      so dropping the icon keeps the UI honest. */}
                  {card.status === "draft" && canManage && (
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      onClick={() =>
                        matchEdit.start(String(card.match_percent))
                      }
                      data-testid="talent-market-btn-edit-match"
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                  )}
                </p>
              )}
            </div>
            {card.published_at && (
              <div>
                <p className="text-muted-foreground">{t("fieldPublishedAt")}</p>
                <p className="font-medium">{formatDate(card.published_at)}</p>
              </div>
            )}
            {/* HRP-92 REDO (round 3 — QA review 2026-06-09): both terminal
                statuses keep their dated row in Details — Completed
                shows "Completed: <date>", Cancelled shows "Cancelled:
                <date>". Round 2 dropped the Cancelled row by mistake;
                QA confirmed the row must come back. Legacy rows that
                pre-date the completed_at / cancelled_at split fall back
                to closed_at so historic data still renders. */}
            {(card.status === "completed" || card.status === "cancelled") &&
              (() => {
                const isCompleted = card.status === "completed";
                const when = isCompleted
                  ? card.completed_at ?? card.closed_at
                  : card.cancelled_at ?? card.closed_at;
                if (!when) return null;
                return (
                  <div>
                    <p className="text-muted-foreground">
                      {isCompleted ? t("statusCompleted") : t("statusCancelled")}
                    </p>
                    <p
                      className="font-medium"
                      data-testid="talent-market-detail-closed-at"
                    >
                      {formatDate(when.slice(0, 10))}
                    </p>
                  </div>
                );
              })()}
          </div>
          {/* HRP-150: status transition commands.
              Draft → Publish + Cancel (HRP-334); Published → Complete +
              Cancel; terminal (Completed / Cancelled) → nothing. */}
          {/* HRP-209: status transitions are admin/manager-only — keeps
              the Employee view read-only until HRP-213 lands. */}
          {canManage && card.status === "draft" && (
            <div className="mt-4 flex gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={publish}
                disabled={saving}
                data-testid="talent-market-detail-publish"
              >
                <Globe className="mr-1 h-4 w-4" />
                {t("actionPublish")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={cancelCard}
                disabled={saving}
                data-testid="talent-market-detail-cancel"
              >
                <XCircle className="mr-1 h-4 w-4" />
                {t("actionCancel")}
              </Button>
            </div>
          )}
          {canManage && card.status === "published" && (
            <div className="mt-4 flex gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={completeCard}
                disabled={saving}
                data-testid="talent-market-detail-complete"
              >
                <CheckCircle2 className="mr-1 h-4 w-4" />
                {t("actionComplete")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={cancelCard}
                disabled={saving}
                data-testid="talent-market-detail-cancel"
              >
                <XCircle className="mr-1 h-4 w-4" />
                {t("actionCancel")}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* HRP-87: structured Required Specialization / Required Competences */}
      <RequiredSpecializationsBlock
        card={card}
        specializations={specializations}
        grades={grades}
        // HRP-209: Employees view requirements but can't edit them —
        // the backend already 403s on the matching endpoints; the
        // readOnly prop hides Add / Edit / Delete affordances in the UI.
        // HRP-291: requirements are editable in Draft only — a card
        // cancelled from Draft is not published but is just as frozen.
        readOnly={card.status !== "draft" || !canManage}
        onChanged={load}
      />
      <RequiredCompetencesBlock
        card={card}
        tree={tree}
        skillLevels={skillLevels}
        competenceById={competenceById}
        readOnly={card.status !== "draft" || !canManage}
        onChanged={load}
      />

      {/* Candidates */}
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div className="flex items-center gap-3">
            <CardTitle className="text-base">{t("candidatesTitle")}</CardTitle>
            {/* HRP-242: "last match" label + refresh icon. Visible to
                every viewer whenever the card carries a stamp; the
                refresh button is hidden on terminal cards and for
                Employee viewers (read-only there). */}
            {(() => {
              const stamp = formatLastMatched(t, card.last_matched_at);
              if (!stamp) return null;
              const refreshable = canManage && !isTerminal;
              return (
                <span
                  className="flex items-center gap-1 text-xs text-muted-foreground"
                  data-testid="talent-market-last-matched"
                >
                  <span title={stamp.tooltip}>
                    {t("lastMatched", { when: stamp.short })}
                  </span>
                  {refreshable && (
                    <button
                      type="button"
                      onClick={refreshMatch}
                      disabled={saving}
                      title={t("recomputeCandidatesTitle")}
                      aria-label={t("refreshCandidatesAria")}
                      className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                      data-testid="talent-market-refresh-candidates"
                    >
                      <RefreshCw className="h-3.5 w-3.5" />
                    </button>
                  )}
                </span>
              );
            })()}
          </div>
          {/* HRP-129: the Candidates block is now auto-populated from the
              card's requirements. The picker stays as a manual override —
              recruiters tweak the auto-pool via Change. HRP-209: the
              button is admin/manager-only — Employees can't add or
              remove candidates. HRP-291: hidden on Completed/Cancelled
              cards — the candidate list is frozen with the card. */}
          {canManage && !isTerminal && (
            <Button
              size="sm"
              variant="outline"
              onClick={openCandidatePicker}
              data-testid={
                card.candidates.length === 0
                  ? "talent-market-candidate-add"
                  : "talent-market-candidate-change"
              }
            >
              <UserPlus className="mr-1 h-4 w-4" />
              {card.candidates.length === 0 ? t("add") : t("change")}
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {card.candidates.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">{t("noCandidates")}</p>
          ) : (
            <div className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{tc("employee")}</TableHead>
                    <TableHead>{t("fieldStatus")}</TableHead>
                    {/* HRP-173 redo: keep the Match column narrow so the
                        right-aligned chips don't drift far away from the
                        Status column. The cell content shrinks to fit. */}
                    <TableHead className="w-[1%] whitespace-nowrap text-right">
                      {t("fieldMatch")}
                    </TableHead>
                    <TableHead>{t("columnActions")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {card.candidates.map((c) => (
                    <TableRow key={c.id} data-testid="talent-market-candidate-row">
                      <TableCell className="text-sm">
                        {/* HRP-149: render "Name Last name" as a Link when the
                            viewer has access to the employee profile (admin /
                            manager-of-division / self), otherwise as plain
                            text (mirrors HRP-85's participant treatment).
                            HRP-209: a quiet "(it's me)" tag follows the
                            viewer's own row so they spot themselves at a
                            glance. HRP-258: the line wraps EmployeeSummaryLine
                            (hideName) so the position + non-active status chip
                            ride underneath the name without leaving the
                            recruiter to cross-reference /employees. */}
                        <div className="flex flex-col gap-0.5">
                          <span className="inline-flex items-center gap-2">
                            {c.can_view_profile ? (
                              <Link
                                href={`/employees/${c.employee_id}`}
                                className="font-medium text-primary underline-offset-2 hover:underline"
                                data-testid="talent-market-candidate-name"
                              >
                                {c.employee_name || c.employee_id}
                              </Link>
                            ) : (
                              <span
                                className="font-medium"
                                data-testid="talent-market-candidate-name"
                              >
                                {c.employee_name || c.employee_id}
                              </span>
                            )}
                            {c.is_me && (
                              <span
                                className="text-xs text-muted-foreground"
                                data-testid="talent-market-candidate-self-tag"
                              >
                                {t("itsMe")}
                              </span>
                            )}
                          </span>
                          <EmployeeSummaryLine
                            employee={{
                              user_name: c.employee_name,
                              position_title: c.position_title,
                              status: c.employee_status,
                            }}
                            hideName
                            data-testid="talent-market-candidate-summary"
                          />
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Badge
                            variant="secondary"
                            className={candidateStatusColors[c.status] || ""}
                            data-testid="talent-market-candidate-status"
                          >
                            {candidateStatusLabel(t, c.status)}
                          </Badge>
                          {/* HRP-213: surface the reacted chip next to the
                              status badge so managers see who already
                              applied. The chip renders the same for the
                              employee (their own row) and the recruiter. */}
                          {c.response_at && (
                            <Badge
                              variant="secondary"
                              className={BADGE_COLOR.blue}
                              data-testid="talent-market-candidate-reacted"
                            >
                              {t("candidateReacted")}
                            </Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell
                        className="w-[1%] whitespace-nowrap tabular-nums"
                        data-testid="talent-market-candidate-match"
                      >
                        <MatchCell
                          item={{
                            comp_match: c.comp_match ?? null,
                            comp_qualifies: c.comp_qualifies ?? false,
                            exp_months: c.exp_months ?? null,
                            exp_qualifies: c.exp_qualifies ?? false,
                            has_comp_requirement:
                              c.has_comp_requirement ?? false,
                            has_spec_requirement:
                              c.has_spec_requirement ?? false,
                            exp_via_current_position:
                              c.exp_via_current_position ?? false,
                          }}
                          onOpen={() =>
                            openMatchDrawer(c.employee_id, c.employee_name)
                          }
                          testIdPrefix="talent-market-candidate"
                          isOpen={
                            drawerOpen && drawerEmployeeId === c.employee_id
                          }
                          // HRP-209: Employees can only open the drawer
                          // on their own row — hide the chevron on
                          // everyone else's. Managers / admins keep
                          // the full breakdown.
                          hideTrigger={!canManage && !c.is_me}
                        />
                      </TableCell>
                      <TableCell>
                        {/* HRP-209: Appoint is admin/manager only — the
                            cell stays empty for plain employees. HRP-291:
                            gone on terminal cards — no appointments on a
                            Completed/Cancelled card. */}
                        {canManage && !isTerminal && c.status !== "appointed" && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() =>
                              setAppointTarget({
                                candidateId: c.id,
                                employeeName: c.employee_name ?? null,
                              })
                            }
                            disabled={saving}
                            data-testid="talent-market-candidate-appoint"
                          >
                            {t("appoint")}
                          </Button>
                        )}
                        {/* HRP-213: an employee viewing their own
                            candidate row gets a React button while
                            (a) the card is Published, (b) they're not
                            yet appointed, and (c) they haven't already
                            reacted. The chip in the Status column
                            covers the "already reacted" state. */}
                        {!canManage &&
                          c.is_me &&
                          card.status === "published" &&
                          c.status !== "appointed" &&
                          !c.response_at && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => setReactConfirmOpen(true)}
                              disabled={saving}
                              data-testid="talent-market-candidate-react"
                            >
                              {t("react")}
                            </Button>
                          )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* HRP-95: Add/Change candidate picker — replaces the legacy UUID
        input. Shows every tenant employee with a computed match score
        and a checkbox column. Add mode hides already-attached rows;
        Change mode includes them, pre-checks, and lets the user
        un-check to delete. Default sort is match desc (server-side);
        the search input narrows by name. */}
      <Dialog open={candOpen} onOpenChange={setCandOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle data-testid="talent-market-change-modal-title">
              {pickerMode === "change"
                ? t("pickerChangeTitle")
                : t("pickerAddTitle")}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              placeholder={t("pickerSearchPlaceholder")}
              value={candidateFilter}
              onChange={(e) => setCandidateFilter(e.target.value)}
              data-testid="talent-market-candidate-search"
            />
            <div className="max-h-[420px] overflow-y-auto rounded-lg border">
              {poolLoading ? (
                <p className="py-8 text-center text-sm text-muted-foreground">
                  {tc("loading")}
                </p>
              ) : (
                (() => {
                  const filterText = candidateFilter.trim().toLowerCase();
                  const filtered = filterText
                    ? pool.filter((p) =>
                        p.name.toLowerCase().includes(filterText),
                      )
                    : pool;
                  if (filtered.length === 0) {
                    return (
                      <p className="py-8 text-center text-sm text-muted-foreground">
                        {pool.length === 0
                          ? t("pickerNoEmployees")
                          : t("pickerNoMatches")}
                      </p>
                    );
                  }
                  return (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-10" />
                          <TableHead>{tc("employee")}</TableHead>
                          <TableHead>{t("fieldStatus")}</TableHead>
                          <TableHead className="text-right">{t("fieldMatch")}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {filtered.map((p) => {
                          const checked = selectedIds.has(p.employee_id);
                          // HRP-214: appointed picker rows are locked —
                          // the recruiter can't uncheck them via the
                          // picker (they have to un-appoint first).
                          const locked = p.status === "appointed";
                          return (
                            <TableRow
                              key={p.employee_id}
                              data-testid="talent-market-candidate-pool-row"
                              data-employee-id={p.employee_id}
                            >
                              <TableCell>
                                <Checkbox
                                  checked={checked}
                                  disabled={locked}
                                  onCheckedChange={() => {
                                    if (locked) return;
                                    toggleCandidate(p.employee_id);
                                  }}
                                  aria-label={t("selectEmployeeAria", {
                                    name: p.name,
                                  })}
                                  // HRP-214 redo (2026-06-09): paint
                                  // appointed (locked) rows in muted
                                  // colours so the user can tell at a
                                  // glance the checkbox is non-actionable
                                  // versus the regular checked rows.
                                  className={
                                    locked
                                      ? "data-checked:border-muted-foreground data-checked:bg-muted data-checked:text-muted-foreground"
                                      : ""
                                  }
                                />
                              </TableCell>
                              <TableCell className="text-sm">
                                <div className="flex flex-col gap-0.5">
                                  <Link
                                    href={`/employees/${p.employee_id}`}
                                    className="font-medium text-primary underline-offset-2 hover:underline"
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    {p.name}
                                  </Link>
                                  {/* HRP-258: same position + status chip
                                      treatment as the Candidates table so
                                      the picker matches the saved view. */}
                                  <EmployeeSummaryLine
                                    employee={{
                                      user_name: p.name,
                                      position_title: p.position_title,
                                      status: p.employee_status,
                                    }}
                                    hideName
                                    data-testid="talent-market-candidate-pool-summary"
                                  />
                                </div>
                              </TableCell>
                              <TableCell>
                                <Badge
                                  variant="secondary"
                                  className={
                                    candidateStatusColors[p.status] ?? ""
                                  }
                                  data-testid="talent-market-candidate-pool-status"
                                >
                                  {candidateStatusLabel(t, p.status)}
                                </Badge>
                              </TableCell>
                              <TableCell className="text-right tabular-nums">
                                <MatchCell
                                  item={p}
                                  onOpen={() =>
                                    openMatchDrawer(p.employee_id, p.name)
                                  }
                                  testIdPrefix="talent-market-candidate-pool"
                                  isOpen={
                                    drawerOpen &&
                                    drawerEmployeeId === p.employee_id
                                  }
                                />
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  );
                })()
              )}
            </div>
          </div>
          <DialogFooter>
            <span
              className="mr-auto text-sm text-muted-foreground"
              data-testid="talent-market-candidate-selected-count"
            >
              {t("selectedCount", { count: selectedIds.size })}
            </span>
            <Button
              variant="outline"
              onClick={() => setCandOpen(false)}
              disabled={saving}
            >
              {tc("cancel")}
            </Button>
            {pickerMode === "change" ? (
              <Button
                onClick={savePicker}
                disabled={saving}
                data-testid="talent-market-change-submit"
              >
                {saving ? t("saving") : t("save")}
              </Button>
            ) : (
              <Button
                onClick={savePicker}
                disabled={saving || selectedIds.size === 0}
                data-testid="talent-market-candidate-add-submit"
              >
                {saving
                  ? t("adding")
                  : selectedIds.size > 1
                    ? t("addN", { count: selectedIds.size })
                    : t("add")}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* HRP-172: per-candidate match breakdown — opened from any
        MatchCell on the page (Candidates table + Add / Change picker
        rows). The drawer fetches its own data, so the page just
        passes the (cardId, employeeId) tuple. */}
      <MatchDrawer
        cardId={id}
        employeeId={drawerEmployeeId}
        employeeName={drawerEmployeeName}
        open={drawerOpen}
        onOpenChange={(o) => {
          setDrawerOpen(o);
        }}
      />

      {/* HRP-215: appoint confirmation so a stray click on the
        Appoint button doesn't pin the candidate. */}
      <ConfirmDialog
        open={appointTarget !== null}
        onOpenChange={(o) => !o && setAppointTarget(null)}
        title={t("appointCandidateTitle")}
        description={
          appointTarget
            ? t("appointConfirm", {
                name: appointTarget.employeeName ?? t("thisCandidate"),
                card: card.title,
              })
            : ""
        }
        confirmLabel={t("appoint")}
        loadingLabel={t("appointing")}
        confirmVariant="default"
        onConfirm={() => {
          if (appointTarget) void appointCandidate(appointTarget.candidateId);
        }}
        loading={saving}
      />

      {/* HRP-213: confirm React before posting — the employee should
          notice the click; there's no undo. */}
      <ConfirmDialog
        open={reactConfirmOpen}
        onOpenChange={(o) => setReactConfirmOpen(o)}
        title={t("sendReactionTitle")}
        description={t("sendReactionConfirm", { title: card.title })}
        confirmLabel={t("send")}
        loadingLabel={t("sending")}
        confirmVariant="default"
        onConfirm={() => void sendReaction()}
        loading={saving}
      />
    </div>
  );
}
