// @vitest-environment jsdom

// HRP-271 — Resume excerpt → parsed-resume focus contract.
//
// Pinned here so the AI Insights → parsed-resume editor wiring keeps
// working: ``extractResumeExcerpts`` must surface the backend-extracted
// citations only for resume_only runs, and the focus event must reach
// the right matched item via the dataset selectors the editor exposes
// (``data-resume-section``, ``data-resume-item-key``,
// ``data-resume-company``, ``data-resume-period``).

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  extractResumeExcerpts,
  type AiAnalysisRun,
  type ResumeExcerpt,
} from "@/lib/recruitment-types";
import {
  RESUME_EXCERPT_FOCUS_EVENT,
  dispatchResumeExcerptFocus,
  type ResumeExcerptFocusDetail,
} from "@/lib/resume-excerpt-focus";

function mkRun(overrides: Partial<AiAnalysisRun> = {}): AiAnalysisRun {
  return {
    id: "run-1",
    candidate_vacancy_id: "cv-1",
    mode: "resume_only",
    status: "completed",
    data_completeness: "partial",
    interview_id: null,
    verdict: "needs_check",
    verdict_summary: null,
    key_strength: null,
    key_risk: null,
    risk_mitigation: null,
    recommendation_for_next_step: null,
    ai_score: null,
    vacancy_profile_version: 1,
    archived_at: null,
    replaced_by_id: null,
    supersedes_id: null,
    created_by_id: null,
    created_at: "2026-06-18T10:00:00Z",
    updated_at: "2026-06-18T10:00:00Z",
    current_stage: "verdict",
    cancelled_at: null,
    cancelled_by_id: null,
    resume_excerpts: null,
    resume_outdated: false,
    ...overrides,
  };
}

function mkExcerpt(overrides: Partial<ResumeExcerpt> = {}): ResumeExcerpt {
  return {
    section: "experience",
    excerpt_text: "Led a team of five engineers",
    source_company: "Acme",
    source_period: "2022 — 2024",
    ...overrides,
  };
}

describe("extractResumeExcerpts", () => {
  it("returns [] for full-mode runs even when resume_excerpts is populated", () => {
    const run = mkRun({ mode: "full", resume_excerpts: [mkExcerpt()] });
    expect(extractResumeExcerpts(run)).toEqual([]);
  });

  it("returns [] when resume_excerpts is null (no citations on the run)", () => {
    expect(extractResumeExcerpts(mkRun())).toEqual([]);
  });

  it("returns the run's resume_excerpts in iteration order", () => {
    const a = mkExcerpt({ excerpt_text: "A" });
    const b = mkExcerpt({ excerpt_text: "B" });
    const c = mkExcerpt({ excerpt_text: "C" });
    const run = mkRun({ resume_excerpts: [a, b, c] });
    expect(extractResumeExcerpts(run).map((e) => e.excerpt_text)).toEqual([
      "A",
      "B",
      "C",
    ]);
  });
});

// ---------------------------------------------------------------------------
// Focus event contract — the parsed-resume editor uses the dataset
// markers below to scroll + highlight the matching block. The selectors
// are part of the public contract between AiInsightsSection and
// ParsedResumeEditor; tests pin them.
// ---------------------------------------------------------------------------

function setupEditorDom(): HTMLDivElement {
  const root = document.createElement("div");
  root.innerHTML = `
    <section data-resume-section="summary"></section>
    <section data-resume-section="experience">
      <ul>
        <li data-resume-item-key="experience-0"
            data-resume-company="Globex"
            data-resume-period="2018 — 2021">Globex 2018 — 2021</li>
        <li data-resume-item-key="experience-1"
            data-resume-company="Acme"
            data-resume-period="2022 — 2024">Lead engineer at Acme. Led a team of five engineers.</li>
      </ul>
    </section>
    <section data-resume-section="skills">
      <span data-resume-item-key="skill-0">TypeScript</span>
      <span data-resume-item-key="skill-1">Python</span>
    </section>
  `;
  document.body.appendChild(root);
  return root;
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("dispatchResumeExcerptFocus", () => {
  it("dispatches a CustomEvent with the excerpt + candidate_id as detail", () => {
    const handler = vi.fn();
    window.addEventListener(RESUME_EXCERPT_FOCUS_EVENT, handler);
    const detail: ResumeExcerptFocusDetail = {
      ...mkExcerpt(),
      candidate_id: "cand-42",
    };
    try {
      dispatchResumeExcerptFocus(detail);
      expect(handler).toHaveBeenCalledTimes(1);
      const evt = handler.mock
        .calls[0][0] as CustomEvent<ResumeExcerptFocusDetail>;
      expect(evt.detail).toEqual(detail);
      expect(evt.detail.candidate_id).toBe("cand-42");
    } finally {
      // HRP-271 (review): try/finally so a failing assertion can't leak
      // the listener into the next test in this file.
      window.removeEventListener(RESUME_EXCERPT_FOCUS_EVENT, handler);
    }
  });
});

describe("parsed-resume editor dataset contract", () => {
  it("exposes the section + item dataset markers the focus handler relies on", () => {
    const root = setupEditorDom();
    expect(
      root.querySelector('[data-resume-section="experience"]'),
    ).not.toBeNull();
    expect(
      root.querySelectorAll(
        '[data-resume-section="experience"] [data-resume-item-key]',
      ),
    ).toHaveLength(2);
    const acme = root.querySelector<HTMLElement>(
      '[data-resume-company="Acme"]',
    );
    expect(acme?.dataset.resumePeriod).toBe("2022 — 2024");
  });

  it("matches an experience excerpt to the item with the same company+period", () => {
    const root = setupEditorDom();
    const section = root.querySelector<HTMLElement>(
      '[data-resume-section="experience"]',
    );
    expect(section).not.toBeNull();
    const items = Array.from(
      section!.querySelectorAll<HTMLElement>("[data-resume-item-key]"),
    );
    const target = items.find(
      (it) =>
        it.dataset.resumeCompany === "Acme" &&
        it.dataset.resumePeriod === "2022 — 2024",
    );
    expect(target?.dataset.resumeItemKey).toBe("experience-1");
  });

  it("matches a skills excerpt whose text is wider than the chip via reverse-substring", () => {
    // HRP-271 (review): when the AI quote is a multi-skill sentence
    // ("Strong TypeScript and Python background"), no single chip's
    // textContent contains the whole quote; the matcher therefore
    // accepts excerpt.includes(item) as well as item.includes(excerpt).
    const root = setupEditorDom();
    const section = root.querySelector<HTMLElement>(
      '[data-resume-section="skills"]',
    );
    const items = Array.from(
      section!.querySelectorAll<HTMLElement>("[data-resume-item-key]"),
    );
    const excerpt = "strong typescript and python background";
    const target = items.find((it) => {
      const text = (it.textContent ?? "").toLowerCase();
      return text.includes(excerpt) || excerpt.includes(text);
    });
    expect(target?.dataset.resumeItemKey).toBe("skill-0");
  });
});
