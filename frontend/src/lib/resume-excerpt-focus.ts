// HRP-271 — loose coupling between AI Insights and the parsed-resume
// editor. AI Insights dispatches ``RESUME_EXCERPT_FOCUS_EVENT`` on
// click; the parsed-resume editor listens on ``window`` and reacts
// (expand section + scroll + highlight). A window event keeps the two
// cards on the candidate page independent of each other's mount state
// and avoids threading a callback through the page-level component.
//
// HRP-680 — the same link, walked the other way. The resume items an
// analysis quoted carry a permanent mark and dispatch
// ``RESUME_CITATION_FOCUS_EVENT``; AI Insights scrolls its citation
// block into view and flashes the matching chip. Without it the only
// clickable end of the pair sat below the thing it scrolled to, which
// read as a one-way jump upward with no way back.
//
// ``candidate_id`` is carried in the detail so a future side-by-side
// candidate comparison view (multiple ParsedResumeEditor instances at
// once) can filter events by candidate without changing the contract.

import type { ParsedResumePayload, ResumeExcerpt } from "./recruitment-types";

export const RESUME_EXCERPT_FOCUS_EVENT = "hrp:resume-excerpt-focus";
export const RESUME_CITATION_FOCUS_EVENT = "hrp:resume-citation-focus";

export interface ResumeExcerptFocusDetail extends ResumeExcerpt {
  candidate_id: string;
}

export function dispatchResumeExcerptFocus(detail: ResumeExcerptFocusDetail): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<ResumeExcerptFocusDetail>(RESUME_EXCERPT_FOCUS_EVENT, {
      detail,
    }),
  );
}

/** HRP-680 — resume item → the chip that quoted it. */
export function dispatchResumeCitationFocus(
  detail: ResumeExcerptFocusDetail,
): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<ResumeExcerptFocusDetail>(RESUME_CITATION_FOCUS_EVENT, {
      detail,
    }),
  );
}

// HRP-271 (review): normalise period strings so LLM-supplied
// ``source_period`` ('2020 - 2022', '2020–2022', 'Mar 2020 — Dec 2022')
// matches the rendered value ('2020 — 2022') regardless of dash variant
// or whitespace. Collapses '—', '–', '-' to a single '-' and strips
// inner whitespace.
export function normalisePeriod(value: string | null | undefined): string {
  if (!value) return "";
  return value
    .toLowerCase()
    .replace(/[‐-―−-]+/g, "-")
    .replace(/\s+/g, "");
}

/**
 * HRP-680 — which rendered resume item does this excerpt quote?
 *
 * The only matcher (HRP-710). It answers both directions of the link:
 * which items carry the permanent mark, and — via the returned key —
 * which node the chip scrolls to, since parsed-resume-editor.tsx looks
 * the item up by ``data-resume-item-key`` rather than walking the DOM
 * with a second copy of these rules.
 *
 * Returns the ``data-resume-item-key`` of the match, or ``null`` when
 * the excerpt cannot be placed — an unplaceable quote gets no mark
 * rather than a misleading one.
 */
export function resumeItemKeyForExcerpt(
  parsed: ParsedResumePayload | null | undefined,
  excerpt: ResumeExcerpt,
): string | null {
  const text = excerpt.excerpt_text?.trim().toLowerCase() ?? "";
  if (!parsed) return null;

  if (excerpt.section === "summary") {
    const summary = (parsed.summary ?? "").toLowerCase();
    return text && summary.includes(text) ? "summary" : null;
  }

  if (excerpt.section === "experience" || excerpt.section === "projects") {
    const entries = parsed.experience ?? [];
    // ``projects`` renders inside the experience section but carries no
    // company/period, so it only gets the substring pass — same carve-out
    // the DOM matcher makes.
    if (excerpt.section === "experience") {
      const wantCompany = excerpt.source_company?.trim().toLowerCase() ?? "";
      const wantPeriod = normalisePeriod(excerpt.source_period);
      const period = (e: (typeof entries)[number]) =>
        normalisePeriod(
          [e.start_date, e.end_date].filter(Boolean).join(" — "),
        );
      const company = (e: (typeof entries)[number]) =>
        (e.company ?? "").toLowerCase();
      const passes: Array<(e: (typeof entries)[number]) => boolean> = [];
      if (wantCompany && wantPeriod) {
        passes.push((e) => company(e) === wantCompany && period(e) === wantPeriod);
      }
      if (wantCompany) passes.push((e) => company(e) === wantCompany);
      if (wantPeriod) passes.push((e) => period(e) === wantPeriod);
      for (const pass of passes) {
        const idx = entries.findIndex(pass);
        if (idx !== -1) return `experience-${idx}`;
      }
    }
    if (!text) return null;
    const idx = entries.findIndex((e) =>
      experienceItemText(e).includes(text),
    );
    return idx === -1 ? null : `experience-${idx}`;
  }

  if (excerpt.section === "skills") {
    const idx = (parsed.skills ?? []).findIndex((s) =>
      overlaps(String(s ?? ""), text),
    );
    return idx === -1 ? null : `skill-${idx}`;
  }

  const idx = (parsed.education ?? []).findIndex((e) =>
    overlaps(
      [e.institution, e.degree, e.field, e.start_date, e.end_date]
        .filter(Boolean)
        .join(" "),
      text,
    ),
  );
  return idx === -1 ? null : `education-${idx}`;
}

/**
 * HRP-680 — every cited item on one resume, keyed by
 * ``data-resume-item-key``.
 *
 * First excerpt wins a contested key: the chips are rendered in the
 * order the analysis produced them, and a second quote landing on an
 * already-marked item would only change which chip the mark links back
 * to, never whether the item is marked.
 */
export function mapExcerptsToResumeItems(
  parsed: ParsedResumePayload | null | undefined,
  excerpts: ResumeExcerpt[] | null | undefined,
): Map<string, ResumeExcerpt> {
  const out = new Map<string, ResumeExcerpt>();
  for (const excerpt of excerpts ?? []) {
    const key = resumeItemKeyForExcerpt(parsed, excerpt);
    if (key !== null && !out.has(key)) out.set(key, excerpt);
  }
  return out;
}

// Mirrors what the experience item actually renders, so the substring
// pass sees the same text the DOM matcher reads off ``textContent``.
function experienceItemText(entry: {
  position?: string | null;
  title?: string | null;
  role?: string | null;
  company?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  description?: string | null;
}): string {
  return [
    entry.position || entry.title || entry.role,
    entry.company,
    [entry.start_date, entry.end_date].filter(Boolean).join(" — "),
    entry.description,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

// Two-way containment: the excerpt may be longer than the item (a
// multi-skill quote vs a single chip) or shorter (a verbatim slice of a
// longer line). A short string (R, Go, C#) only counts as contained when
// it matches a whole token — bare `includes` let the letter "r" inside
// "redis" claim the citation for the "R" chip (HRP-654 review).
function overlaps(itemText: string, excerpt: string): boolean {
  const item = itemText.trim().toLowerCase();
  const quote = excerpt.trim().toLowerCase();
  if (!item || !quote) return false;
  return contains(item, quote) || contains(quote, item);
}

// Below this length the needle must match a whole token of the haystack.
// "+", "#" and "." stay word characters so C++, C# and Node.js survive
// tokenization as single skills.
const MIN_SUBSTRING_LENGTH = 4;

function contains(haystack: string, needle: string): boolean {
  if (needle.length >= MIN_SUBSTRING_LENGTH) return haystack.includes(needle);
  return haystack.split(/[^a-z0-9+#.]+/).includes(needle);
}
