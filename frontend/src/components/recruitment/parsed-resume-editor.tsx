"use client";

/**
 * Inline editor for ``parsed_resume_jsonb`` sections on the candidate
 * card. Each section toggles between read mode and a per-section edit
 * form; Save replaces just that section, rebuilds the full payload via
 * ``updateParsedResumeSection``, and PATCHes ``/candidates/{id}`` with
 * the current ``If-Match`` ETag. The detail page owns the card state
 * and reapplies the response when ``onSaved`` fires.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { useTranslations } from "next-intl";
import {
  Award,
  ChevronDown,
  GraduationCap,
  Languages as LanguagesIcon,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { API_BASE, ApiError } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import {
  emptyCertificate,
  emptyEducation,
  emptyExperience,
  emptyLanguage,
  type ParsedResumeSectionKey,
  updateParsedResumeSection,
} from "@/lib/recruitment-helpers";
import type {
  CandidateCanonical,
  CandidateCanonicalCard,
  ParsedResumeCertificate,
  ParsedResumeEducation,
  ParsedResumeExperience,
  ParsedResumeLanguage,
  ResumeExcerptSection,
} from "@/lib/recruitment-types";
import {
  RESUME_EXCERPT_FOCUS_EVENT,
  type ResumeExcerptFocusDetail,
} from "@/lib/resume-excerpt-focus";
import { cn } from "@/lib/utils";

interface Props {
  card: CandidateCanonicalCard;
  etag: string | null;
  onSaved: (next: CandidateCanonical, etag: string | null) => void;
}

// HRP-271: section keys for the collapse state map. Includes
// ``summary`` even though it isn't a ``ParsedResumeSectionKey`` (which
// only covers editable list sections).
type CollapseKey =
  | "summary"
  | "experience"
  | "education"
  | "skills"
  | "languages"
  | "certificates";

// HRP-271: map an excerpt section to a parsed-resume section the
// editor actually renders. ``projects`` isn't a separate section here,
// so we fall back to ``experience`` (where projects are typically
// described).
function mapExcerptSection(section: ResumeExcerptSection): CollapseKey {
  if (section === "projects") return "experience";
  return section;
}

// HRP-271: 2 s transient focus ring applied to the matched item or
// section block. Tailwind atomic classes are listed as string literals
// here so the JIT picks them up at build time.
const HIGHLIGHT_CLASSES = [
  "ring-2",
  "ring-amber-400",
  "ring-offset-2",
  "rounded-md",
  "transition-all",
  "duration-200",
];
const HIGHLIGHT_DURATION_MS = 2000;

// HRP-271 (review): normalise period strings so LLM-supplied
// ``source_period`` ('2020 - 2022', '2020–2022', 'Mar 2020 — Dec 2022')
// matches the DOM dataset value ('2020 — 2022') regardless of dash
// variant or whitespace. Collapses '—', '–', '-' to a single '-' and
// strips inner whitespace.
function normalisePeriod(value: string | null | undefined): string {
  if (!value) return "";
  return value
    .toLowerCase()
    .replace(/[‐-―−-]+/g, "-")
    .replace(/\s+/g, "");
}

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function findExperienceTarget(
  section: HTMLElement,
  detail: ResumeExcerptFocusDetail,
): HTMLElement | null {
  const items = Array.from(
    section.querySelectorAll<HTMLElement>("[data-resume-item-key]"),
  );
  if (items.length === 0) return null;
  const wantCompany = detail.source_company?.trim().toLowerCase() ?? "";
  const wantPeriod = normalisePeriod(detail.source_period);
  const excerpt = detail.excerpt_text.trim().toLowerCase();
  // Prefer the strongest signal first — company+period, then company,
  // then period, then a substring match anywhere in the rendered item.
  if (wantCompany && wantPeriod) {
    for (const it of items) {
      const company = (it.dataset.resumeCompany ?? "").toLowerCase();
      const period = normalisePeriod(it.dataset.resumePeriod);
      if (company === wantCompany && period === wantPeriod) return it;
    }
  }
  if (wantCompany) {
    for (const it of items) {
      const company = (it.dataset.resumeCompany ?? "").toLowerCase();
      if (company === wantCompany) return it;
    }
  }
  if (wantPeriod) {
    for (const it of items) {
      const period = normalisePeriod(it.dataset.resumePeriod);
      if (period === wantPeriod) return it;
    }
  }
  if (excerpt) {
    for (const it of items) {
      const text = (it.textContent ?? "").toLowerCase();
      if (text.includes(excerpt)) return it;
    }
  }
  // No signal matched — return null so the caller scrolls to the
  // section header instead of misleading the recruiter with an
  // arbitrary items[0] highlight.
  return null;
}

function findGenericTarget(
  section: HTMLElement,
  detail: ResumeExcerptFocusDetail,
): HTMLElement | null {
  const items = Array.from(
    section.querySelectorAll<HTMLElement>("[data-resume-item-key]"),
  );
  if (items.length === 0) return null;
  const excerpt = detail.excerpt_text.trim().toLowerCase();
  if (!excerpt) return null;
  // Try both directions: the excerpt may be longer than the item
  // (multi-skill quote vs single chip) or shorter (verbatim chunk of
  // a longer description). Either substring is a positive match.
  for (const it of items) {
    const text = (it.textContent ?? "").toLowerCase();
    if (text.includes(excerpt) || excerpt.includes(text)) return it;
  }
  return null;
}

export function ParsedResumeEditor({ card, etag, onSaved }: Props) {
  const t = useTranslations("recruitment");
  const parsed = card.parsed_resume_jsonb ?? null;
  const candidateId = card.id;
  const containerRef = useRef<HTMLDivElement>(null);
  const highlightStateRef = useRef<{
    el: HTMLElement;
    timer: number;
  } | null>(null);
  const [collapsed, setCollapsed] = useState<Record<CollapseKey, boolean>>({
    summary: false,
    experience: false,
    education: false,
    skills: false,
    languages: false,
    certificates: false,
  });

  const toggleCollapsed = useCallback((key: CollapseKey) => {
    setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  // HRP-271 (review): each highlight tracks its own timer so a second
  // click cancels the pending classList.remove before scheduling a
  // fresh one, and unmount cleanup clears any in-flight timer instead
  // of letting it fire on a detached node.
  const applyHighlight = useCallback((el: HTMLElement) => {
    const pending = highlightStateRef.current;
    if (pending) {
      window.clearTimeout(pending.timer);
      if (pending.el !== el) {
        pending.el.classList.remove(...HIGHLIGHT_CLASSES);
      }
    }
    el.classList.add(...HIGHLIGHT_CLASSES);
    const timer = window.setTimeout(() => {
      el.classList.remove(...HIGHLIGHT_CLASSES);
      if (highlightStateRef.current?.timer === timer) {
        highlightStateRef.current = null;
      }
    }, HIGHLIGHT_DURATION_MS);
    highlightStateRef.current = { el, timer };
  }, []);

  useEffect(() => {
    // Cleanup any pending highlight timer on unmount so it doesn't
    // mutate a detached DOM node.
    return () => {
      const pending = highlightStateRef.current;
      if (pending) {
        window.clearTimeout(pending.timer);
        highlightStateRef.current = null;
      }
    };
  }, []);

  // HRP-271: listen for ``resume-excerpt-focus`` events from
  // AiInsightsSection. Synchronously expand the matching section via
  // ``flushSync`` (avoids the rAF-before-commit race), then locate the
  // most specific DOM item and scroll+highlight it. Falls back to the
  // section block when no item matches — never to an arbitrary
  // ``items[0]`` (that would mislead the recruiter).
  useEffect(() => {
    function handle(evt: Event) {
      const detail = (evt as CustomEvent<ResumeExcerptFocusDetail>).detail;
      if (!detail || detail.candidate_id !== candidateId) return;
      if (!containerRef.current) return;
      const key = mapExcerptSection(detail.section);
      // ``flushSync`` forces React to commit the collapsed→expanded
      // transition before we query the DOM, so the section body is
      // guaranteed to be mounted regardless of the dispatch context.
      flushSync(() => {
        setCollapsed((prev) =>
          prev[key] ? { ...prev, [key]: false } : prev,
        );
      });
      const root = containerRef.current;
      if (!root) return;
      const section = root.querySelector<HTMLElement>(
        `[data-resume-section="${key}"]`,
      );
      if (!section) return;
      let target: HTMLElement = section;
      if (key !== "summary") {
        // ``projects`` excerpts route through the experience section
        // (closest semantic match) but typically lack source_company /
        // source_period — so we use the substring matcher instead of
        // the company+period one to avoid a wrong company match.
        const matcher =
          key === "experience" && detail.section !== "projects"
            ? findExperienceTarget
            : findGenericTarget;
        target = matcher(section, detail) ?? section;
      }
      target.scrollIntoView({
        block: "center",
        behavior: prefersReducedMotion() ? "auto" : "smooth",
      });
      applyHighlight(target);
    }
    window.addEventListener(RESUME_EXCERPT_FOCUS_EVENT, handle);
    return () =>
      window.removeEventListener(RESUME_EXCERPT_FOCUS_EVENT, handle);
  }, [applyHighlight, candidateId]);

  async function patchSection<K extends ParsedResumeSectionKey>(
    section: K,
    value: Parameters<typeof updateParsedResumeSection<K>>[2],
  ): Promise<void> {
    const nextPayload = updateParsedResumeSection(parsed, section, value);
    const token = getAccessToken();
    const res = await fetch(`${API_BASE}/recruitment/candidates/${card.id}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(etag ? { "If-Match": etag } : {}),
      },
      body: JSON.stringify({ parsed_resume_jsonb: nextPayload }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      throw new ApiError(
        res.status,
        typeof body.detail === "string" ? body.detail : res.statusText,
        body.detail,
      );
    }
    const data = (await res.json()) as CandidateCanonical;
    onSaved(data, res.headers.get("ETag"));
    toast.success(t("resumeEditorToastSectionUpdated"));
  }

  return (
    <Card data-testid="candidate-card-section-resume" ref={containerRef}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <Sparkles className="size-4 text-primary" /> {t("resumeEditorTitle")}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6 text-sm">
        {!parsed && (
          <p className="text-muted-foreground">
            {t("resumeEditorNoParsedResume")}
          </p>
        )}
        <SummaryEditor
          value={parsed?.summary ?? null}
          collapsed={collapsed.summary}
          onToggleCollapsed={() => toggleCollapsed("summary")}
          onSave={(v) => patchSection("summary", v)}
        />
        <ExperienceEditor
          value={parsed?.experience ?? []}
          collapsed={collapsed.experience}
          onToggleCollapsed={() => toggleCollapsed("experience")}
          onSave={(v) => patchSection("experience", v)}
        />
        <EducationEditor
          value={parsed?.education ?? []}
          collapsed={collapsed.education}
          onToggleCollapsed={() => toggleCollapsed("education")}
          onSave={(v) => patchSection("education", v)}
        />
        <SkillsEditor
          value={parsed?.skills ?? []}
          collapsed={collapsed.skills}
          onToggleCollapsed={() => toggleCollapsed("skills")}
          onSave={(v) => patchSection("skills", v)}
        />
        <LanguagesEditor
          value={parsed?.languages ?? []}
          collapsed={collapsed.languages}
          onToggleCollapsed={() => toggleCollapsed("languages")}
          onSave={(v) => patchSection("languages", v)}
        />
        <CertificatesEditor
          value={parsed?.certificates ?? []}
          collapsed={collapsed.certificates}
          onToggleCollapsed={() => toggleCollapsed("certificates")}
          onSave={(v) => patchSection("certificates", v)}
        />
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Shared header — read/edit toggle. Each section owns its own draft state
// so cancelling does not leak partial edits across sections.
// ---------------------------------------------------------------------------

interface SectionHeaderProps {
  title: string;
  testId: string;
  editing: boolean;
  busy: boolean;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onEdit: () => void;
  onCancel: () => void;
  onSave: () => void;
  saveDisabled?: boolean;
}

function SectionHeader({
  title,
  testId,
  editing,
  busy,
  collapsed,
  onToggleCollapsed,
  onEdit,
  onCancel,
  onSave,
  saveDisabled,
}: SectionHeaderProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  // HRP-271 (review): keep the heading element for screen-reader
  // outline navigation. The disclosure button lives inside the <h3>
  // (standard ARIA disclosure pattern) so "H" jumps still land on
  // every section.
  return (
    <div className="flex items-center justify-between gap-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        <button
          type="button"
          onClick={onToggleCollapsed}
          className="flex items-center gap-1 hover:text-foreground"
          aria-expanded={!collapsed}
          data-testid={`${testId}-toggle`}
        >
          <ChevronDown
            className={cn(
              "size-3 transition-transform",
              collapsed && "-rotate-90",
            )}
            aria-hidden
          />
          <span>{title}</span>
        </button>
      </h3>
      {editing ? (
        <div className="flex gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={onCancel}
            disabled={busy}
            data-testid={`${testId}-cancel`}
          >
            {tc("cancel")}
          </Button>
          <Button
            size="sm"
            onClick={onSave}
            disabled={busy || saveDisabled}
            data-testid={`${testId}-save`}
          >
            {busy ? t("actionSaving") : t("save")}
          </Button>
        </div>
      ) : (
        <Button
          variant="ghost"
          size="sm"
          onClick={onEdit}
          data-testid={`${testId}-edit`}
        >
          {t("actionEdit")}
        </Button>
      )}
    </div>
  );
}

// HRP-271 (review): Edit click must auto-expand the section, otherwise
// ``editing=true`` + ``collapsed=true`` leaves the user staring at
// Save/Cancel with no input rendered.
function startEditing(
  collapsed: boolean,
  onToggleCollapsed: () => void,
  setEditing: (v: boolean) => void,
): void {
  if (collapsed) onToggleCollapsed();
  setEditing(true);
}

function useEditState<T>(value: T) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<T>(value);
  const [busy, setBusy] = useState(false);
  // Re-sync the draft from the latest server value while not actively
  // editing. React's documented "syncing derived state" pattern calls
  // ``setState`` during render guarded by a memoised previous value.
  const [prevValue, setPrevValue] = useState(value);
  if (!editing && value !== prevValue) {
    setPrevValue(value);
    setDraft(value);
  }
  return { editing, setEditing, draft, setDraft, busy, setBusy };
}

// HRP-476: module-scope helper, so the caller hands its own ``t`` in
// rather than calling ``useTranslations`` outside a component.
async function runSave(
  t: (key: string) => string,
  setBusy: (b: boolean) => void,
  setEditing: (b: boolean) => void,
  fn: () => Promise<void>,
) {
  setBusy(true);
  try {
    await fn();
    setEditing(false);
  } catch (err) {
    if (err instanceof ApiError && err.status === 412) {
      toast.error(t("resumeEditorConflictReload"));
    } else {
      toast.error(
        err instanceof Error ? err.message : t("resumeEditorSaveFailed"),
      );
    }
  } finally {
    setBusy(false);
  }
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------

function SummaryEditor({
  value,
  collapsed,
  onToggleCollapsed,
  onSave,
}: {
  value: string | null;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onSave: (v: string | null) => Promise<void>;
}) {
  const t = useTranslations("recruitment");
  const { editing, setEditing, draft, setDraft, busy, setBusy } =
    useEditState<string | null>(value);

  return (
    <section
      className="space-y-2"
      data-testid="candidate-card-edit-summary"
      data-resume-section="summary"
    >
      <SectionHeader
        title={t("resumeEditorSectionSummary")}
        testId="candidate-card-edit-summary"
        editing={editing}
        busy={busy}
        collapsed={collapsed}
        onToggleCollapsed={onToggleCollapsed}
        onEdit={() => startEditing(collapsed, onToggleCollapsed, setEditing)}
        onCancel={() => setEditing(false)}
        onSave={() => runSave(t, setBusy, setEditing, () => onSave(draft))}
      />
      {!collapsed &&
        (editing ? (
          <Textarea
            rows={4}
            value={draft ?? ""}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={t("resumeEditorSummaryPlaceholder")}
            data-testid="candidate-card-edit-summary-input"
          />
        ) : value ? (
          <p className="whitespace-pre-line text-foreground/90">{value}</p>
        ) : (
          <p className="text-xs text-muted-foreground">
            {t("resumeEditorSummaryEmpty")}
          </p>
        ))}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Skills — chip input with comma/enter add
// ---------------------------------------------------------------------------

function SkillsEditor({
  value,
  collapsed,
  onToggleCollapsed,
  onSave,
}: {
  value: string[];
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onSave: (v: string[]) => Promise<void>;
}) {
  const t = useTranslations("recruitment");
  const { editing, setEditing, draft, setDraft, busy, setBusy } =
    useEditState<string[]>(value);
  const [pending, setPending] = useState("");

  function addPending() {
    const cleaned = pending.trim();
    if (!cleaned) return;
    setDraft((prev) =>
      prev.includes(cleaned) ? prev : [...prev, cleaned],
    );
    setPending("");
  }

  return (
    <section
      className="space-y-2"
      data-testid="candidate-card-edit-skills"
      data-resume-section="skills"
    >
      <SectionHeader
        title={t("resumeEditorSectionSkills")}
        testId="candidate-card-edit-skills"
        editing={editing}
        busy={busy}
        collapsed={collapsed}
        onToggleCollapsed={onToggleCollapsed}
        onEdit={() => startEditing(collapsed, onToggleCollapsed, setEditing)}
        onCancel={() => setEditing(false)}
        onSave={() => runSave(t, setBusy, setEditing, () => onSave(draft))}
      />
      {!collapsed &&
        (editing ? (
          <div className="space-y-2">
            <div className="flex flex-wrap gap-1">
              {draft.map((s, idx) => (
                <Badge
                  key={`${s}-${idx}`}
                  variant="secondary"
                  className="cursor-pointer text-[11px]"
                  onClick={() =>
                    setDraft((prev) => prev.filter((x) => x !== s))
                  }
                  data-testid={`candidate-card-edit-skills-chip-${idx}`}
                  data-resume-item-key={`skill-${idx}`}
                >
                  {s} ×
                </Badge>
              ))}
            </div>
            <Input
              value={pending}
              onChange={(e) => setPending(e.target.value)}
              placeholder={t("resumeEditorSkillsPlaceholder")}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === ",") {
                  e.preventDefault();
                  addPending();
                }
              }}
              onBlur={addPending}
              data-testid="candidate-card-edit-skills-input"
            />
          </div>
        ) : value.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {value.map((s, idx) => (
              <Badge
                key={`${s}-${idx}`}
                variant="secondary"
                className="text-[11px]"
                data-resume-item-key={`skill-${idx}`}
              >
                {s}
              </Badge>
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            {t("resumeEditorSkillsEmpty")}
          </p>
        ))}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Experience — list of {title, company, dates, description}
// ---------------------------------------------------------------------------

function ExperienceEditor({
  value,
  collapsed,
  onToggleCollapsed,
  onSave,
}: {
  value: ParsedResumeExperience[];
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onSave: (v: ParsedResumeExperience[]) => Promise<void>;
}) {
  const t = useTranslations("recruitment");
  const { editing, setEditing, draft, setDraft, busy, setBusy } =
    useEditState<ParsedResumeExperience[]>(value);

  function patchItem(i: number, patch: Partial<ParsedResumeExperience>) {
    setDraft((prev) =>
      prev.map((it, idx) => (idx === i ? { ...it, ...patch } : it)),
    );
  }

  return (
    <section
      className="space-y-2"
      data-testid="candidate-card-edit-experience"
      data-resume-section="experience"
    >
      <SectionHeader
        title={t("resumeEditorSectionExperience")}
        testId="candidate-card-edit-experience"
        editing={editing}
        busy={busy}
        collapsed={collapsed}
        onToggleCollapsed={onToggleCollapsed}
        onEdit={() => startEditing(collapsed, onToggleCollapsed, setEditing)}
        onCancel={() => setEditing(false)}
        onSave={() => runSave(t, setBusy, setEditing, () => onSave(draft))}
      />
      {!collapsed && (editing ? (
        <div className="space-y-3">
          {draft.map((exp, i) => (
            <div
              key={i}
              className="space-y-2 rounded-md border p-3"
              data-testid={`candidate-card-edit-experience-${i}`}
              data-resume-item-key={`experience-${i}`}
              data-resume-company={exp.company ?? ""}
              data-resume-period={[exp.start_date, exp.end_date]
                .filter(Boolean)
                .join(" — ")}
            >
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <FieldInput
                  label={t("resumeEditorFieldPosition")}
                  value={exp.position ?? exp.title ?? exp.role ?? ""}
                  onChange={(v) =>
                    patchItem(i, { position: v, role: v, title: v })
                  }
                  testId={`candidate-card-edit-experience-${i}-title`}
                />
                <FieldInput
                  label={t("resumeEditorFieldCompany")}
                  value={exp.company ?? ""}
                  onChange={(v) => patchItem(i, { company: v })}
                  testId={`candidate-card-edit-experience-${i}-company`}
                />
                <FieldInput
                  label={t("resumeEditorFieldStartDate")}
                  value={exp.start_date ?? ""}
                  onChange={(v) => patchItem(i, { start_date: v })}
                  testId={`candidate-card-edit-experience-${i}-start`}
                />
                <FieldInput
                  label={t("resumeEditorFieldEndDate")}
                  value={exp.end_date ?? ""}
                  onChange={(v) => patchItem(i, { end_date: v })}
                  testId={`candidate-card-edit-experience-${i}-end`}
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">
                  {t("resumeEditorFieldDescription")}
                </Label>
                <Textarea
                  rows={3}
                  value={exp.description ?? ""}
                  onChange={(e) =>
                    patchItem(i, { description: e.target.value })
                  }
                  data-testid={`candidate-card-edit-experience-${i}-description`}
                />
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  setDraft((prev) => prev.filter((_, j) => j !== i))
                }
                data-testid={`candidate-card-edit-experience-${i}-remove`}
              >
                <Trash2 className="mr-1 size-3" /> {t("resumeEditorRemove")}
              </Button>
            </div>
          ))}
          <Button
            variant="outline"
            size="sm"
            onClick={() => setDraft((prev) => [...prev, emptyExperience()])}
            data-testid="candidate-card-edit-experience-add"
          >
            <Plus className="mr-1 size-3" /> {t("resumeEditorAddExperience")}
          </Button>
        </div>
      ) : value.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          {t("resumeEditorExperienceEmpty")}
        </p>
      ) : (
        <ul className="space-y-3">
          {value.map((exp, i) => {
            const period = [exp.start_date, exp.end_date]
              .filter(Boolean)
              .join(" — ");
            return (
              <li
                key={i}
                className="rounded-md border-l-2 border-primary/40 pl-3"
                data-resume-item-key={`experience-${i}`}
                data-resume-company={exp.company ?? ""}
                data-resume-period={period}
              >
                <p className="font-medium">
                  {exp.position ||
                    exp.title ||
                    exp.role ||
                    t("resumeEditorRoleFallback")}
                  {exp.company ? ` @ ${exp.company}` : ""}
                </p>
                <p className="text-xs text-muted-foreground">{period}</p>
                {exp.description && (
                  <p className="mt-1 whitespace-pre-line text-sm text-foreground/90">
                    {exp.description}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      ))}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Education
// ---------------------------------------------------------------------------

function EducationEditor({
  value,
  collapsed,
  onToggleCollapsed,
  onSave,
}: {
  value: ParsedResumeEducation[];
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onSave: (v: ParsedResumeEducation[]) => Promise<void>;
}) {
  const t = useTranslations("recruitment");
  const { editing, setEditing, draft, setDraft, busy, setBusy } =
    useEditState<ParsedResumeEducation[]>(value);

  function patchItem(i: number, patch: Partial<ParsedResumeEducation>) {
    setDraft((prev) =>
      prev.map((it, idx) => (idx === i ? { ...it, ...patch } : it)),
    );
  }

  return (
    <section
      className="space-y-2"
      data-testid="candidate-card-edit-education"
      data-resume-section="education"
    >
      <SectionHeader
        title={t("resumeEditorSectionEducation")}
        testId="candidate-card-edit-education"
        editing={editing}
        busy={busy}
        collapsed={collapsed}
        onToggleCollapsed={onToggleCollapsed}
        onEdit={() => startEditing(collapsed, onToggleCollapsed, setEditing)}
        onCancel={() => setEditing(false)}
        onSave={() => runSave(t, setBusy, setEditing, () => onSave(draft))}
      />
      {!collapsed && (editing ? (
        <div className="space-y-3">
          {draft.map((edu, i) => (
            <div
              key={i}
              className="space-y-2 rounded-md border p-3"
              data-testid={`candidate-card-edit-education-${i}`}
              data-resume-item-key={`education-${i}`}
            >
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <FieldInput
                  label={t("resumeEditorFieldInstitution")}
                  value={edu.institution ?? ""}
                  onChange={(v) => patchItem(i, { institution: v })}
                  testId={`candidate-card-edit-education-${i}-institution`}
                />
                <FieldInput
                  label={t("resumeEditorFieldDegree")}
                  value={edu.degree ?? ""}
                  onChange={(v) => patchItem(i, { degree: v })}
                  testId={`candidate-card-edit-education-${i}-degree`}
                />
                <FieldInput
                  label={t("resumeEditorFieldField")}
                  value={edu.field ?? ""}
                  onChange={(v) => patchItem(i, { field: v })}
                  testId={`candidate-card-edit-education-${i}-field`}
                />
                <div className="grid grid-cols-2 gap-2">
                  <FieldInput
                    label={t("resumeEditorFieldStart")}
                    value={edu.start_date ?? ""}
                    onChange={(v) => patchItem(i, { start_date: v })}
                    testId={`candidate-card-edit-education-${i}-start`}
                  />
                  <FieldInput
                    label={t("resumeEditorFieldEnd")}
                    value={edu.end_date ?? ""}
                    onChange={(v) => patchItem(i, { end_date: v })}
                    testId={`candidate-card-edit-education-${i}-end`}
                  />
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  setDraft((prev) => prev.filter((_, j) => j !== i))
                }
                data-testid={`candidate-card-edit-education-${i}-remove`}
              >
                <Trash2 className="mr-1 size-3" /> {t("resumeEditorRemove")}
              </Button>
            </div>
          ))}
          <Button
            variant="outline"
            size="sm"
            onClick={() => setDraft((prev) => [...prev, emptyEducation()])}
            data-testid="candidate-card-edit-education-add"
          >
            <Plus className="mr-1 size-3" /> {t("resumeEditorAddEducation")}
          </Button>
        </div>
      ) : value.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          {t("resumeEditorEducationEmpty")}
        </p>
      ) : (
        <ul className="space-y-2">
          {value.map((edu, i) => (
            <li
              key={i}
              className="flex items-start gap-2"
              data-resume-item-key={`education-${i}`}
            >
              <GraduationCap className="mt-0.5 size-4 text-muted-foreground" />
              <div>
                <p className="font-medium">
                  {edu.institution || t("resumeEditorFieldInstitution")}
                  {edu.degree ? ` — ${edu.degree}` : ""}
                </p>
                <p className="text-xs text-muted-foreground">
                  {[edu.field, edu.start_date, edu.end_date]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
            </li>
          ))}
        </ul>
      ))}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Languages — list of {name, level}
// ---------------------------------------------------------------------------

function LanguagesEditor({
  value,
  collapsed,
  onToggleCollapsed,
  onSave,
}: {
  value: ParsedResumeLanguage[];
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onSave: (v: ParsedResumeLanguage[]) => Promise<void>;
}) {
  const t = useTranslations("recruitment");
  const { editing, setEditing, draft, setDraft, busy, setBusy } =
    useEditState<ParsedResumeLanguage[]>(value);

  function patchItem(i: number, patch: Partial<ParsedResumeLanguage>) {
    setDraft((prev) =>
      prev.map((it, idx) => (idx === i ? { ...it, ...patch } : it)),
    );
  }

  return (
    <section
      className="space-y-2"
      data-testid="candidate-card-edit-languages"
      data-resume-section="languages"
    >
      <SectionHeader
        title={t("resumeEditorSectionLanguages")}
        testId="candidate-card-edit-languages"
        editing={editing}
        busy={busy}
        collapsed={collapsed}
        onToggleCollapsed={onToggleCollapsed}
        onEdit={() => startEditing(collapsed, onToggleCollapsed, setEditing)}
        onCancel={() => setEditing(false)}
        onSave={() => runSave(t, setBusy, setEditing, () => onSave(draft))}
      />
      {!collapsed && (editing ? (
        <div className="space-y-2">
          {draft.map((lang, i) => (
            <div
              key={i}
              className="grid grid-cols-[1fr_120px_auto] items-end gap-2"
              data-testid={`candidate-card-edit-languages-${i}`}
              data-resume-item-key={`language-${i}`}
            >
              <FieldInput
                label={t("fieldName")}
                value={lang.name ?? ""}
                onChange={(v) => patchItem(i, { name: v })}
                testId={`candidate-card-edit-languages-${i}-name`}
              />
              <FieldInput
                label={t("resumeEditorFieldLevel")}
                value={lang.level ?? ""}
                onChange={(v) => patchItem(i, { level: v })}
                testId={`candidate-card-edit-languages-${i}-level`}
              />
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() =>
                  setDraft((prev) => prev.filter((_, j) => j !== i))
                }
                aria-label={t("resumeEditorRemoveLanguage")}
                data-testid={`candidate-card-edit-languages-${i}-remove`}
              >
                <Trash2 className="size-3" />
              </Button>
            </div>
          ))}
          <Button
            variant="outline"
            size="sm"
            onClick={() => setDraft((prev) => [...prev, emptyLanguage()])}
            data-testid="candidate-card-edit-languages-add"
          >
            <Plus className="mr-1 size-3" /> {t("resumeEditorAddLanguage")}
          </Button>
        </div>
      ) : value.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          {t("resumeEditorLanguagesEmpty")}
        </p>
      ) : (
        <ul className="flex flex-wrap items-center gap-2 text-sm">
          {value.map((l, i) => (
            <li
              key={i}
              className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs"
              data-resume-item-key={`language-${i}`}
            >
              <LanguagesIcon className="size-3" />
              {l.name}
              {l.level ? ` · ${l.level}` : ""}
            </li>
          ))}
        </ul>
      ))}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Certificates
// ---------------------------------------------------------------------------

function CertificatesEditor({
  value,
  collapsed,
  onToggleCollapsed,
  onSave,
}: {
  value: ParsedResumeCertificate[];
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onSave: (v: ParsedResumeCertificate[]) => Promise<void>;
}) {
  const t = useTranslations("recruitment");
  const { editing, setEditing, draft, setDraft, busy, setBusy } =
    useEditState<ParsedResumeCertificate[]>(value);

  function patchItem(i: number, patch: Partial<ParsedResumeCertificate>) {
    setDraft((prev) =>
      prev.map((it, idx) => (idx === i ? { ...it, ...patch } : it)),
    );
  }

  return (
    <section
      className="space-y-2"
      data-testid="candidate-card-edit-certificates"
      data-resume-section="certificates"
    >
      <SectionHeader
        title={t("resumeEditorSectionCertificates")}
        testId="candidate-card-edit-certificates"
        editing={editing}
        busy={busy}
        collapsed={collapsed}
        onToggleCollapsed={onToggleCollapsed}
        onEdit={() => startEditing(collapsed, onToggleCollapsed, setEditing)}
        onCancel={() => setEditing(false)}
        onSave={() => runSave(t, setBusy, setEditing, () => onSave(draft))}
      />
      {!collapsed && (editing ? (
        <div className="space-y-3">
          {draft.map((cert, i) => (
            <div
              key={i}
              className="space-y-2 rounded-md border p-3"
              data-testid={`candidate-card-edit-certificates-${i}`}
              data-resume-item-key={`certificate-${i}`}
            >
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                <FieldInput
                  label={t("fieldName")}
                  value={cert.name ?? ""}
                  onChange={(v) => patchItem(i, { name: v })}
                  testId={`candidate-card-edit-certificates-${i}-name`}
                />
                <FieldInput
                  label={t("resumeEditorFieldIssuer")}
                  value={cert.issuer ?? ""}
                  onChange={(v) => patchItem(i, { issuer: v })}
                  testId={`candidate-card-edit-certificates-${i}-issuer`}
                />
                <FieldInput
                  label={t("resumeEditorFieldIssued")}
                  value={cert.issued_at ?? ""}
                  onChange={(v) => patchItem(i, { issued_at: v })}
                  testId={`candidate-card-edit-certificates-${i}-issued`}
                />
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  setDraft((prev) => prev.filter((_, j) => j !== i))
                }
                data-testid={`candidate-card-edit-certificates-${i}-remove`}
              >
                <Trash2 className="mr-1 size-3" /> {t("resumeEditorRemove")}
              </Button>
            </div>
          ))}
          <Button
            variant="outline"
            size="sm"
            onClick={() => setDraft((prev) => [...prev, emptyCertificate()])}
            data-testid="candidate-card-edit-certificates-add"
          >
            <Plus className="mr-1 size-3" /> {t("resumeEditorAddCertificate")}
          </Button>
        </div>
      ) : value.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          {t("resumeEditorCertificatesEmpty")}
        </p>
      ) : (
        <ul className="list-disc space-y-1 pl-5 text-foreground/90">
          {value.map((c, i) => (
            <li
              key={i}
              className="flex items-start gap-2"
              data-resume-item-key={`certificate-${i}`}
            >
              <Award className="mt-1 size-3 text-muted-foreground" />
              <span>
                {c.name}
                {c.issuer ? ` — ${c.issuer}` : ""}
                {c.issued_at ? ` (${c.issued_at})` : ""}
              </span>
            </li>
          ))}
        </ul>
      ))}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Small input wrapper to keep the per-section editors compact.
// ---------------------------------------------------------------------------

function FieldInput({
  label,
  value,
  onChange,
  testId,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  testId: string;
}) {
  const id = useMemo(() => `${testId}-id`, [testId]);
  return (
    <div className="space-y-1">
      <Label className="text-xs" htmlFor={id}>
        {label}
      </Label>
      <Input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        data-testid={testId}
      />
    </div>
  );
}
