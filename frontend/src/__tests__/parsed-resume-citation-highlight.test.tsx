// @vitest-environment jsdom
//
// HRP-680 (redo) — what the Parsed resume card highlights, and when.
//
// The shipped build marked every cited entry the moment the card
// opened, in a grey wash. Two consequences, both reported: the resume
// read as a page of hits before anybody had clicked anything, and a
// chip click landed the reader on a target that looked exactly like its
// already-marked neighbours. This suite mounts the real editor and
// pins the corrected behaviour: nothing marked on open, and a click
// marking the quoted words — only those, only in that entry.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import { RESUME_EXCERPT_FOCUS_EVENT } from "@/lib/resume-excerpt-focus";
import type {
  CandidateCanonicalCard,
  ResumeExcerpt,
} from "@/lib/recruitment-types";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const { ParsedResumeEditor } = await import(
  "@/components/recruitment/parsed-resume-editor"
);

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  // jsdom ships neither of these and the focus handler calls both.
  Element.prototype.scrollIntoView = vi.fn();
  window.matchMedia = vi.fn().mockReturnValue({ matches: false }) as never;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const SUMMARY =
  "Backend developer with three years on customer-support SaaS. " +
  "Python and Django services, REST APIs.";
const DESCRIPTION =
  "Built and maintained REST endpoints for the ticket-routing service " +
  "in Python and Django. Added Redis caching.";

const CARD = {
  id: "cand-1",
  tenant_id: "t-1",
  full_name: "Priya Shah",
  email: null,
  phone: null,
  linkedin_url: null,
  location: null,
  current_position: null,
  years_of_experience: 3,
  source: null,
  notes: null,
  archived_at: null,
  created_at: "2026-08-01T10:00:00Z",
  updated_at: "2026-08-01T10:00:00Z",
  vacancy_applications: [],
  candidate_files: [],
  parsed_resume_jsonb: {
    summary: SUMMARY,
    experience: [
      {
        position: "Software Developer",
        company: "Freshworks",
        start_date: "2023",
        end_date: null,
        description: DESCRIPTION,
      },
    ],
    education: [
      {
        institution: "PES University",
        degree: "BTech",
        field: "Computer Science",
        start_date: "2018",
        end_date: "2022",
      },
    ],
    skills: ["Python", "Django", "REST APIs"],
    languages: [],
    certificates: [],
  },
} as unknown as CandidateCanonicalCard;

// Three citations, so "only the target" is a claim with something to
// contrast against.
const EXCERPTS: ResumeExcerpt[] = [
  {
    section: "summary",
    excerpt_text: "Python and Django services",
    source_company: null,
    source_period: null,
  },
  {
    section: "experience",
    excerpt_text: "Added Redis caching.",
    source_company: "Freshworks",
    source_period: "2023",
  },
  {
    section: "skills",
    excerpt_text: "Python",
    source_company: null,
    source_period: null,
  },
] as unknown as ResumeExcerpt[];

async function render(excerpts: ResumeExcerpt[] = EXCERPTS) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <ParsedResumeEditor
          card={CARD}
          etag={null}
          onSaved={() => {}}
          excerpts={excerpts}
        />
      </NextIntlClientProvider>,
    );
  });
}

async function clickChip(excerpt: ResumeExcerpt) {
  await act(async () => {
    window.dispatchEvent(
      new CustomEvent(RESUME_EXCERPT_FOCUS_EVENT, {
        detail: { ...excerpt, candidate_id: "cand-1" },
      }),
    );
  });
}

const marks = () => [...container.querySelectorAll("mark")];

describe("Parsed resume — citation highlight (HRP-680 redo)", () => {
  it("marks nothing until a chip asks for it", async () => {
    await render();
    expect(marks()).toHaveLength(0);
  });

  it("keeps a quiet marker on cited entries without a background", async () => {
    await render();
    const markers = container.querySelectorAll(
      '[data-testid="candidate-card-resume-cited-marker"]',
    );
    // One per cited entry — the link is still discoverable while reading.
    expect(markers.length).toBe(3);
    const cited = container.querySelector<HTMLElement>(
      '[data-resume-cited="true"]',
    )!;
    // The reported symptom was a permanent wash; a hover affordance is
    // fine, a painted-on background is not.
    expect(cited.className).not.toMatch(/(^|\s)bg-/);
    expect(cited.className).not.toMatch(/ring-1/);
  });

  it("marks the quoted words, and only those, on a chip click", async () => {
    await render();
    await clickChip(EXCERPTS[1]);

    const found = marks();
    expect(found).toHaveLength(1);
    expect(found[0].textContent).toBe("Added Redis caching.");
    // Inside the entry the chip pointed at, not next to it.
    expect(found[0].closest("[data-resume-item-key]")?.getAttribute(
      "data-resume-item-key",
    )).toBe("experience-0");
  });

  it("leaves the other cited entries alone", async () => {
    await render();
    await clickChip(EXCERPTS[0]);

    const found = marks();
    expect(found).toHaveLength(1);
    expect(found[0].closest("[data-resume-item-key]")?.getAttribute(
      "data-resume-item-key",
    )).toBe("summary");
    // The skills chip quotes "Python", which also appears in the summary
    // sentence — the mark must not leak into an entry nobody selected.
    const skill = container.querySelector<HTMLElement>(
      '[data-resume-item-key="skill-0"]',
    )!;
    expect(skill.querySelector("mark")).toBeNull();
  });

  it("moves the mark rather than accumulating it", async () => {
    await render();
    await clickChip(EXCERPTS[1]);
    await clickChip(EXCERPTS[2]);

    const found = marks();
    expect(found).toHaveLength(1);
    expect(found[0].closest("[data-resume-item-key]")?.getAttribute(
      "data-resume-item-key",
    )).toBe("skill-0");
  });

  it("marks the right words when lowercasing changes the length", async () => {
    // "İ".toLowerCase() is two code units, so folding the whole string and
    // slicing the original by the folded offset slides the mark one char
    // to the right. Real input: a Turkish institution name above the
    // quoted line.
    const card = JSON.parse(JSON.stringify(CARD));
    card.parsed_resume_jsonb.experience[0].description =
      "İstanbul Tech — Added Redis caching.";
    await act(async () => {
      root.render(
        <NextIntlClientProvider locale="en" messages={enMessages}>
          <ParsedResumeEditor
            card={card as CandidateCanonicalCard}
            etag={null}
            onSaved={() => {}}
            excerpts={[EXCERPTS[1]]}
          />
        </NextIntlClientProvider>,
      );
    });
    await clickChip(EXCERPTS[1]);

    const found = marks();
    expect(found).toHaveLength(1);
    expect(found[0].textContent).toBe("Added Redis caching.");
  });

  it("falls back to the section when the quote is not in the entry", async () => {
    // A paraphrase: the matcher still places it by company + period, but
    // there is no substring to mark.
    const paraphrase = {
      section: "experience",
      excerpt_text: "Reduced the busiest endpoint's latency substantially",
      source_company: "Freshworks",
      source_period: "2023",
    } as unknown as ResumeExcerpt;
    await render([paraphrase]);
    await clickChip(paraphrase);

    expect(marks()).toHaveLength(0);
    const section = container.querySelector<HTMLElement>(
      '[data-resume-section="experience"]',
    )!;
    expect(section.className).toContain("ring-amber-400");
  });
});
