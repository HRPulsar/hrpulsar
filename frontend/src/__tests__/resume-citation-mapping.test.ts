// HRP-680 — the resume item ↔ citation chip correspondence.
//
// The mark on a quoted resume item and the chip it links back to are
// only useful if they agree with the forward direction (chip → resume),
// which since HRP-710 is the same function: the editor scrolls to the
// ``data-resume-item-key`` this returns. This pins the priority order:
// company + period first,
// then company, then period, then a substring pass — and pins the
// refusal to guess, which is what keeps an unplaceable quote from
// marking an arbitrary item.

import { describe, expect, it } from "vitest";
import {
  mapExcerptsToResumeItems,
  normalisePeriod,
  resumeItemKeyForExcerpt,
} from "@/lib/resume-excerpt-focus";
import type {
  ParsedResumePayload,
  ResumeExcerpt,
} from "@/lib/recruitment-types";

const RESUME: ParsedResumePayload = {
  summary: "Nine years in payments. Studying distributed systems on the side.",
  experience: [
    {
      position: "Staff Engineer",
      role: "Staff Engineer",
      company: "Klarna",
      start_date: "2021",
      end_date: null,
      description: "Owned the reconciliation pipeline end to end.",
    },
    {
      position: "Senior Backend Engineer",
      role: "Senior Backend Engineer",
      company: "Klarna",
      start_date: "2018",
      end_date: "2021",
      description: "Built the ledger service on PostgreSQL.",
    },
    {
      position: "Backend Engineer",
      role: "Backend Engineer",
      company: "SoundCloud",
      start_date: "2016",
      end_date: "2018",
      description: "Python services behind the creator dashboard.",
    },
  ],
  education: [
    {
      institution: "TU Berlin",
      degree: "MSc",
      field: "Computer Science",
      start_date: "2013",
      end_date: "2016",
    },
  ],
  skills: ["Python", "PostgreSQL", "Kafka"],
};

function excerpt(over: Partial<ResumeExcerpt>): ResumeExcerpt {
  return {
    section: "experience",
    excerpt_text: "",
    source_company: null,
    source_period: null,
    ...over,
  };
}

describe("normalisePeriod", () => {
  it("collapses dash variants and whitespace", () => {
    expect(normalisePeriod("2018 — 2021")).toBe("2018-2021");
    expect(normalisePeriod("2018 – 2021")).toBe("2018-2021");
    expect(normalisePeriod("2018-2021")).toBe("2018-2021");
    expect(normalisePeriod(null)).toBe("");
  });
});

describe("resumeItemKeyForExcerpt", () => {
  it("prefers company + period over company alone", () => {
    // Two Klarna rows — only the period tells them apart.
    expect(
      resumeItemKeyForExcerpt(
        RESUME,
        excerpt({ source_company: "Klarna", source_period: "2018 — 2021" }),
      ),
    ).toBe("experience-1");
  });

  it("falls back to company when the period does not match any row", () => {
    expect(
      resumeItemKeyForExcerpt(
        RESUME,
        excerpt({ source_company: "Klarna", source_period: "1999" }),
      ),
    ).toBe("experience-0");
  });

  it("matches on period alone when no company is given", () => {
    expect(
      resumeItemKeyForExcerpt(RESUME, excerpt({ source_period: "2016 — 2018" })),
    ).toBe("experience-2");
  });

  it("falls back to a substring of the rendered item", () => {
    expect(
      resumeItemKeyForExcerpt(
        RESUME,
        excerpt({ excerpt_text: "Built the ledger service on PostgreSQL." }),
      ),
    ).toBe("experience-1");
  });

  it("places summary, skills and education quotes", () => {
    expect(
      resumeItemKeyForExcerpt(
        RESUME,
        excerpt({
          section: "summary",
          excerpt_text: "Studying distributed systems on the side.",
        }),
      ),
    ).toBe("summary");
    expect(
      resumeItemKeyForExcerpt(
        RESUME,
        excerpt({ section: "skills", excerpt_text: "Kafka" }),
      ),
    ).toBe("skill-2");
    expect(
      resumeItemKeyForExcerpt(
        RESUME,
        excerpt({ section: "education", excerpt_text: "TU Berlin" }),
      ),
    ).toBe("education-0");
  });

  it("routes a projects quote through experience by substring only", () => {
    // ``projects`` carries no company/period, so a company that would
    // have matched under ``experience`` must not be consulted.
    expect(
      resumeItemKeyForExcerpt(
        RESUME,
        excerpt({ section: "projects", source_company: "Klarna" }),
      ),
    ).toBeNull();
    expect(
      resumeItemKeyForExcerpt(
        RESUME,
        excerpt({
          section: "projects",
          excerpt_text: "Python services behind the creator dashboard.",
        }),
      ),
    ).toBe("experience-2");
  });

  it("does not let a short skill chip claim an unrelated quote", () => {
    // Bare two-way `includes` let the letter "r" inside "redis" bind a
    // citation to the "R" chip (HRP-654 review): a short chip must match
    // a whole token of the excerpt, in either direction.
    const withShortSkills: ParsedResumePayload = {
      ...RESUME,
      skills: ["R", "Python", "Django"],
    };
    expect(
      resumeItemKeyForExcerpt(
        withShortSkills,
        excerpt({ section: "skills", excerpt_text: "Python, Django, Redis" }),
      ),
    ).toBe("skill-1");
    // The short chip still wins its own token…
    expect(
      resumeItemKeyForExcerpt(
        withShortSkills,
        excerpt({ section: "skills", excerpt_text: "R, dplyr" }),
      ),
    ).toBe("skill-0");
    // …and "C#"-style chips survive tokenization.
    expect(
      resumeItemKeyForExcerpt(
        { ...RESUME, skills: ["C#", "SQL"] },
        excerpt({ section: "skills", excerpt_text: "C#, .NET" }),
      ),
    ).toBe("skill-0");
  });

  it("refuses to guess rather than marking the wrong item", () => {
    expect(
      resumeItemKeyForExcerpt(
        RESUME,
        excerpt({ excerpt_text: "Nothing in this resume says that." }),
      ),
    ).toBeNull();
    expect(
      resumeItemKeyForExcerpt(
        RESUME,
        excerpt({ section: "summary", excerpt_text: "not in the summary" }),
      ),
    ).toBeNull();
    expect(resumeItemKeyForExcerpt(null, excerpt({ excerpt_text: "x" }))).toBe(
      null,
    );
  });
});

describe("mapExcerptsToResumeItems", () => {
  it("keys every placeable excerpt and drops the rest", () => {
    const map = mapExcerptsToResumeItems(RESUME, [
      excerpt({ source_company: "SoundCloud" }),
      excerpt({ section: "skills", excerpt_text: "Python" }),
      excerpt({ excerpt_text: "unplaceable" }),
    ]);
    expect([...map.keys()].sort()).toEqual(["experience-2", "skill-0"]);
  });

  it("keeps the first excerpt when two land on the same item", () => {
    const first = excerpt({
      source_company: "Klarna",
      source_period: "2021",
      excerpt_text: "first",
    });
    const second = excerpt({
      source_company: "Klarna",
      source_period: "2021",
      excerpt_text: "second",
    });
    const map = mapExcerptsToResumeItems(RESUME, [first, second]);
    expect(map.get("experience-0")?.excerpt_text).toBe("first");
  });

  it("is empty when there is no analysis", () => {
    expect(mapExcerptsToResumeItems(RESUME, []).size).toBe(0);
    expect(mapExcerptsToResumeItems(RESUME, undefined).size).toBe(0);
  });
});
