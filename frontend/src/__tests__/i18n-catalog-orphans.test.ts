/**
 * Review §3: the catalog→code direction. `i18n-message-keys.test.ts` proves
 * every key the code asks for exists; nothing proved the reverse, so a
 * component that was deleted or rewritten left its messages behind —
 * ~22 `recruitment.resumeSplit*` / verdict / toast keys survived their
 * screens and had to be translated into every locale forever.
 *
 * Heuristic: a leaf key of en.json counts as used when its last segment
 * appears somewhere in frontend/src as a quoted identifier — `"seg"`,
 * `'seg'`, `` `seg` `` — or inside a dotted quoted path (`"ns.seg"`).
 * That is deliberately loose: it only asks whether the name is written
 * down anywhere, so a key shared by several call sites, passed through a
 * `*_KEYS` map or held in a variable still counts. It is tight enough to
 * catch the case that actually happens — the last reference to a name
 * disappearing with its component.
 *
 * Keys assembled at runtime (`` t(`issue_${code}`) ``) have no literal
 * anywhere, so their prefixes are allowlisted below. Only the `en`
 * catalog is scanned; the parity guard makes the others carry the same
 * key set.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(__dirname, "..");
const EN_CATALOG = resolve(__dirname, "../../messages/en.json");

/**
 * Dotted key prefixes whose leaves are composed at runtime, each with the
 * call site that builds them. An entry here is a promise that the segment
 * after the prefix is a wire code (an enum, a finding code, a billing
 * action) rather than something a developer typed into `t("…")`.
 */
const DYNAMIC_KEY_PREFIXES = [
  // app/(dashboard)/dashboard/page.tsx — t(`stage_${stage.key}`),
  // t(`finding_${finding.code}`) and the three sibling families.
  "dashboard.stage_",
  "dashboard.finding_",
  "dashboard.findingCta_",
  "dashboard.myFinding_",
  "dashboard.myFindingCta_",
  // app/(dashboard)/employees/page.tsx — t(`issue_${issue.code}`).
  "employees.issue_",
  // app/(dashboard)/development/page.tsx — t(`flag_${f}`).
  "development.flag_",
  // lib/billing-labels.ts — t(`${prefix}.${code}`) over the credits.yaml
  // catalog; settings/billing/transactions — t(`billingCreditType.${…}`).
  "settings.billingCategory.",
  "settings.billingAction.",
  "settings.billingCreditType.",
  // app/(platform)/platform/tenants/[id] — t(`brandingThemeName_${name}`).
  "platform.brandingThemeName_",
  // lib/reference-labels.ts — resolve(t, `assessmentStatus.${code}`),
  // `assessmentType.${type_code}` and `scaleLevel.${system_code}`, keyed
  // by the backend's reference codes.
  "reference.assessmentStatus.",
  "reference.assessmentType.",
  "reference.scaleLevel.",
  // app/(dashboard)/analytics/page.tsx — t(`hrMetric_${m.code}`) and
  // t(`hrMetricWhy_${m.code}`).
  "analytics.hrMetric_",
  "analytics.hrMetricWhy_",
  // components/coverage/* — every Coverage label is an enum rendered as
  // t(`<group>_${code}`) against the work/coverage wire vocabulary.
  "coverage.type_",
  "coverage.typeHint_",
  "coverage.status_",
  "coverage.state_",
  "coverage.responsibility_",
  "coverage.reversibility_",
  "coverage.output_",
  "coverage.gapLabel_",
  "coverage.hireRoute_",
  "coverage.hireRouteHint_",
  "coverage.mode_",
  "coverage.quality_",
  "coverage.verdict_",
  "coverage.humanLabel_",
  "coverage.accessLog_",
  "coverage.skillStatus_",
];

type Catalog = { [key: string]: string | Catalog };

function leafKeys(tree: Catalog, prefix = ""): string[] {
  return Object.entries(tree).flatMap(([key, value]) => {
    const dotted = prefix ? `${prefix}.${key}` : key;
    return typeof value === "string" ? [dotted] : leafKeys(value, dotted);
  });
}

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) out.push(...sourceFiles(path));
    else if (/\.tsx?$/.test(name)) out.push(path);
  }
  return out;
}

/**
 * Identifier-shaped text between quotes, dotted paths included. Matching
 * only this shape is what keeps the scan aligned: a className, a URL or a
 * sentence never matches, so its quotes are never consumed and the next
 * real key literal is still found.
 */
const QUOTED_IDENTIFIER = /["'`]([A-Za-z_][A-Za-z0-9_.]*)["'`]/g;

export function quotedTokens(source: string): Set<string> {
  const out = new Set<string>();
  for (const match of source.matchAll(QUOTED_IDENTIFIER)) {
    out.add(match[1]);
    for (const part of match[1].split(".")) out.add(part);
  }
  return out;
}

const EN = JSON.parse(readFileSync(EN_CATALOG, "utf8")) as Catalog;
const KEYS = leafKeys(EN);

const TOKENS = new Set<string>();
for (const file of sourceFiles(SRC)) {
  // Do not let this file's own examples answer for the catalog.
  if (file === __filename) continue;
  for (const token of quotedTokens(readFileSync(file, "utf8"))) {
    TOKENS.add(token);
  }
}

export function isOrphan(key: string, tokens: Set<string>): boolean {
  if (DYNAMIC_KEY_PREFIXES.some((prefix) => key.startsWith(prefix))) {
    return false;
  }
  return !tokens.has(key.split(".").pop()!);
}

describe("en.json carries no message the code stopped asking for", () => {
  it("scans a plausible number of literals", () => {
    // Tripwire: a scan that silently matched nothing would pass vacuously.
    expect(TOKENS.size).toBeGreaterThan(2000);
    expect(KEYS.length).toBeGreaterThan(1000);
  });

  it("finds no orphaned key", () => {
    expect(
      KEYS.filter((key) => isOrphan(key, TOKENS)),
      "these catalog keys are named nowhere in frontend/src — delete them " +
        "from every messages/*.json, or, if they are composed at runtime, " +
        "add their prefix to DYNAMIC_KEY_PREFIXES with the call site",
    ).toEqual([]);
  });

  it("keeps every allowlisted prefix pointing at real keys", () => {
    const stale = DYNAMIC_KEY_PREFIXES.filter(
      (prefix) => !KEYS.some((key) => key.startsWith(prefix)),
    );
    expect(
      stale,
      "DYNAMIC_KEY_PREFIXES names a family the catalog no longer has — " +
        "drop the entry so the allowlist cannot hide a future orphan",
    ).toEqual([]);
  });
});

describe("the scanner catches a violation", () => {
  it("reports a key nothing names", () => {
    expect(isOrphan("recruitment.resumeSplitTabFile", new Set(["other"]))).toBe(
      true,
    );
  });

  it("accepts a key named in a plain call", () => {
    const tokens = quotedTokens('t("resumeSplitTabFile");');
    expect(isOrphan("recruitment.resumeSplitTabFile", tokens)).toBe(false);
  });

  it("accepts a key named through its dotted path", () => {
    const tokens = quotedTokens('t("recruitment.resumeSplitTabFile");');
    expect(tokens.has("resumeSplitTabFile")).toBe(true);
  });

  it("does not let a sentence swallow the next key literal", () => {
    const tokens = quotedTokens('<p title="a long, quoted sentence">{t("someKey")}</p>');
    expect(tokens.has("someKey")).toBe(true);
  });

  it("exempts a runtime-composed family", () => {
    expect(isOrphan("employees.issue_pdp_overdue", new Set())).toBe(false);
  });
});
