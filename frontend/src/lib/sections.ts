/**
 * HRP-820: the sections the tenant's access matrix knows. The codes are the
 * sidebar ids and what /auth/me `sections` is keyed by; the backend registry
 * (backend/app/core/sections.py) is the source of truth for the API side.
 */
export const SECTION_CODES = [
  "employees",
  "company",
  "assessments",
  "development",
  "exams",
  "competences",
  "coverage",
  "talent-market",
  "recruitment",
  "analytics",
  "dictionaries",
  "import",
  "invitations",
  "roles",
  "ai-settings",
] as const;

export type SectionCode = (typeof SECTION_CODES)[number];
export type SectionLevel = "view" | "manage";

/** Route segment(s) under (dashboard) → the section the page belongs to.
 *  Anything not listed (dashboard, onboarding, personal settings, billing)
 *  is outside the matrix. */
const ROUTE_SECTIONS: Record<string, SectionCode> = {
  employees: "employees",
  "admin/employees": "employees",
  company: "company",
  assessments: "assessments",
  "assessment-groups": "assessments",
  development: "development",
  exams: "exams",
  competences: "competences",
  coverage: "coverage",
  "talent-market": "talent-market",
  recruitment: "recruitment",
  analytics: "analytics",
  dictionaries: "dictionaries",
  "settings/import": "import",
  "settings/invitations": "invitations",
  "settings/roles": "roles",
  "settings/ai": "ai-settings",
};

export function sectionForPath(pathname: string): SectionCode | null {
  // HRP-823: /exams renders one's own exams whatever the matrix says, the
  // page-side of `/api/exams*` being in PERSONAL_PATHS - an assignment
  // e-mail links straight here. The same path one segment deeper is a
  // different thing, the mass exam's own page, and stays gated (at
  // `manage`, which that page asks for itself).
  if (pathname === "/exams") return null;
  // /employees/me is outside the matrix by itself, mirroring PERSONAL_PATHS
  // in app/core/sections.py. The page only resolves the id and redirects to
  // the canonical /employees/{id}, which both the SPA and the backend do
  // gate - the same accepted consequence as one's own PDP. The other
  // personal routes there have no page of their own to gate.
  if (pathname === "/employees/me") return null;
  const [first = "", second = ""] = pathname.replace(/^\//, "").split("/");
  return ROUTE_SECTIONS[`${first}/${second}`] ?? ROUTE_SECTIONS[first] ?? null;
}
