/**
 * HRP-511 (a): every message key the frontend asks for must exist in the
 * catalog — the counterpart of the backend's
 * test_every_translate_key_is_catalogued.
 *
 * The parity guard proves the locales agree with each other; nothing
 * proved they agree with the *code*. A renamed or deleted key rendered
 * the raw dotted string in the UI and no test noticed.
 *
 * Two populations are scanned:
 *
 *   1. Literal calls — `t("someKey")`, resolved through the namespace of
 *      the `useTranslations("ns")` / `getTranslations("ns")` binding in
 *      the same file, including `.rich` / `.markup` / `.raw` / `.has`.
 *   2. Key maps — the `*_KEY` / `*_KEYS` constants that feed `t(dynamic)`
 *      call sites (ASSESSMENT_STATUS_KEYS, AI_ANALYSIS_STAGE_LABEL_KEYS
 *      and ~50 siblings). A literal scan cannot see through them, so each
 *      one is registered with the namespace its values belong to. Maps
 *      holding something other than message keys (env names, billing
 *      action codes, level tokens) are registered as `null`.
 *
 * Registration is optional and content-based: a constant is only judged
 * against the catalog when its values already read as catalog keys, so an
 * unrelated QUERY_KEYS/STORAGE_KEYS added on another branch never fails
 * this file. Registering a map upgrades it to a strict every-value check.
 *
 * Only `en` is checked: the parity guard makes every other catalog carry
 * the same key set.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(__dirname, "..");
const EN_CATALOG = resolve(__dirname, "../../messages/en.json");

type Catalog = { [key: string]: string | Catalog };

function flatten(tree: Catalog, prefix = ""): Set<string> {
  const out = new Set<string>();
  for (const [key, value] of Object.entries(tree)) {
    const dotted = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") out.add(dotted);
    else for (const nested of flatten(value, dotted)) out.add(nested);
  }
  return out;
}

const EN_TREE = JSON.parse(readFileSync(EN_CATALOG, "utf8")) as Catalog;
const EN = flatten(EN_TREE);
/** Top-level catalog namespaces, the candidates a bare key resolves in. */
const NAMESPACES = Object.keys(EN_TREE).filter(
  (key) => typeof EN_TREE[key] === "object",
);

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (name === "__tests__") continue;
      out.push(...sourceFiles(path));
    } else if (/\.tsx?$/.test(name)) {
      out.push(path);
    }
  }
  return out;
}

const FILES = sourceFiles(SRC);
const rel = (path: string) => path.slice(SRC.length - "src".length);

// --- 1. literal t("key") calls ---------------------------------------

const HOOK_RE =
  /(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:await\s+)?(?:useTranslations|getTranslations)\s*\(\s*(?:"([^"]*)"|'([^']*)')?\s*\)/g;

/** Translator binding → namespace it was created with ("" = catalog root). */
export function translatorScopes(source: string): Map<string, string> {
  const scopes = new Map<string, string>();
  for (const match of source.matchAll(HOOK_RE)) {
    scopes.set(match[1], match[2] ?? match[3] ?? "");
  }
  return scopes;
}

/** Fully-qualified keys of every literal translator call in `source`.
 * Dynamic arguments (variables, template literals) are skipped — they are
 * covered by the key-map registry below. */
export function literalMessageKeys(source: string): string[] {
  const keys: string[] = [];
  for (const [binding, namespace] of translatorScopes(source)) {
    const callRe = new RegExp(
      `\\b${binding}(?:\\.rich|\\.markup|\\.raw|\\.has)?\\s*\\(\\s*["']([A-Za-z0-9_.]+)["']`,
      "g",
    );
    for (const match of source.matchAll(callRe)) {
      keys.push(namespace ? `${namespace}.${match[1]}` : match[1]);
    }
  }
  return keys;
}

// --- 2. key maps feeding dynamic t() calls ----------------------------

const DECL_RE =
  /(?:export\s+)?const\s+([A-Za-z0-9_$]*KEY[A-Za-z0-9_$]*)\b[^=]{0,300}=\s*([[{])/g;

/** Object properties whose value is never a message key. */
const NON_KEY_PROPS = new Set([
  "value",
  "key",
  "code",
  "id",
  "href",
  "url",
  "path",
  "testId",
  "icon",
  "color",
  "variant",
  "className",
]);

/** A catalog leaf name: camelCase or snake_case identifier. Filters out
 * class names ("bg-red-500"), storage keys ("hrpulsar:draft:") and
 * SCREAMING_ENV_NAMES before they are ever looked up. */
const KEY_SHAPED = /^[a-z][A-Za-z0-9_]*$/;

/**
 * `<src-relative path>::<CONST>` → catalog namespace its values live in.
 *
 * Registration is not mandatory (see the classification tests below): it
 * upgrades a map to a strict "every value must resolve" check.
 */
const MESSAGE_KEY_MAPS: Record<string, string> = {
  "src/app/(auth)/register/request-access-form.tsx::ROLE_LABEL_KEY": "auth",
  "src/app/(dashboard)/assessments/[id]/page.tsx::STATUS_ACTION_KEYS": "assessments",
  "src/app/(dashboard)/assessments/mass-create-dialog.tsx::TYPE_OPTION_KEYS": "assessments",
  "src/app/(dashboard)/assessments/page.tsx::TYPE_OPTION_KEYS": "assessments",
  "src/app/(dashboard)/exams/status.ts::STATUS_KEYS": "exams",
  "src/app/(dashboard)/settings/ai/page.tsx::PRESET_LABEL_KEY": "settings",
  "src/app/(dashboard)/settings/ai/page.tsx::PRESET_DESCRIPTION_KEY": "settings",
  "src/app/(dashboard)/talent-market/[id]/page.tsx::STATUS_KEYS": "talentMarket",
  "src/app/(dashboard)/talent-market/[id]/page.tsx::CANDIDATE_STATUS_KEYS": "talentMarket",
  "src/app/(dashboard)/talent-market/[id]/page.tsx::MONTH_SHORT_KEYS": "talentMarket",
  "src/app/(dashboard)/talent-market/page.tsx::TYPE_KEYS": "talentMarket",
  "src/app/(dashboard)/talent-market/page.tsx::STATUS_KEYS": "talentMarket",
  "src/app/(dashboard)/talent-market/page.tsx::STATUS_FILTER_KEYS": "talentMarket",
  "src/components/ai-generation-banner.tsx::SCOPE_LABEL_KEY": "common",
  "src/components/ai-generation-banner.tsx::STATUS_LABEL_KEY": "common",
  "src/components/assessment/assessment-detailed-results.tsx::ROLE_KEYS": "assessments",
  "src/components/assessment/criteria-summary.tsx::CRITERIA_TYPE_KEYS": "assessments",
  "src/components/competence/usage-warning.tsx::AREA_LABEL_KEYS": "competences",
  "src/components/competence-generation/ActiveSessionConflictDialog.tsx::SCOPE_LABEL_KEYS": "common",
  "src/components/competence-generation/ActiveSessionConflictDialog.tsx::STATUS_LABEL_KEYS": "common",
  "src/components/competence-generation/ErrorScreen.tsx::MESSAGE_KEYS": "competences",
  "src/components/employees/employee-status.ts::STATUS_KEYS": "employees",
  "src/components/header.tsx::SEGMENT_KEYS": "sidebar",
  "src/components/positions/PositionStatusBadge.tsx::STATUS_LABEL_KEY": "company",
  "src/components/recruitment/ai-insights-section.tsx::STALENESS_TEXT_KEYS": "recruitment",
  "src/components/recruitment/ai-insights-section.tsx::SECTION_LABEL_KEYS": "recruitment",
  "src/components/recruitment/ai-verdict-badge.tsx::READINESS_TEXT_KEYS": "recruitment",
  "src/components/recruitment/profile-generation-dialog.tsx::GENERATION_STEP_KEYS": "recruitment",
  "src/components/recruitment/profile-generation-status.tsx::GENERATION_STEP_KEYS": "recruitment",
  "src/components/specialization/ai-history-tab.tsx::STATUS_LABEL_KEY": "company",
  "src/components/specialization/positions-summary.tsx::STATUS_LABEL_KEY": "company",
  "src/lib/assessment-status.ts::ASSESSMENT_STATUS_KEYS": "assessments",
  "src/lib/candidate-source.ts::CANDIDATE_SOURCE_KEYS": "recruitment",
  "src/lib/matrix-grading.ts::COVERAGE_GAP_KEYS": "company",
  "src/lib/pdp-status.ts::PDP_STATUS_KEYS": "development",
  "src/lib/pdp-status.ts::PDP_STATUS_ACTION_KEYS": "development",
  "src/lib/question-enums.ts::GOAL_LABEL_KEYS": "recruitment",
  "src/lib/question-enums.ts::PRIORITY_LABEL_KEYS": "recruitment",
  "src/lib/question-enums.ts::SOURCE_LABEL_KEYS": "recruitment",
  "src/lib/recruitment-types.ts::AI_ANALYSIS_STAGE_LABEL_KEYS": "recruitment",
  "src/lib/recruitment-types.ts::AI_VERDICT_LABEL_KEYS": "recruitment",
  "src/lib/recruitment-types.ts::AI_NEXT_STEP_LABEL_KEYS": "recruitment",
  "src/lib/types.ts::MATRIX_AI_STATUS_LABEL_KEYS": "recruitment",
  "src/lib/types.ts::CANDIDATE_VACANCY_STATUS_LABEL_KEYS": "recruitment",
  "src/lib/types.ts::REPORT_SECTION_LABEL_KEYS": "recruitment",
  "src/lib/types.ts::REPORT_STATUS_LABEL_KEYS": "recruitment",
  "src/lib/user-role-label.ts::SYSTEM_ROLE_KEYS": "sidebar",
  "src/lib/vacancy-status.ts::VACANCY_STATUS_BADGE_KEYS": "recruitment",
  "src/lib/vacancy-status.ts::VACANCY_STATUS_OPTION_KEYS": "recruitment",
};

/**
 * The `{...}`/`[...]` literal starting at `openIndex`.
 *
 * Brackets inside string literals and comments do not count — a value
 * like `"{count} left"` used to unbalance the counter and swallow the
 * rest of the file (review finding 5).
 */
export function blockAt(source: string, openIndex: number): string {
  let depth = 0;
  let quote: string | null = null;
  let comment: "line" | "block" | null = null;
  for (let i = openIndex; i < source.length; i++) {
    const char = source[i];
    const next = source[i + 1];
    if (quote) {
      if (char === "\\") i++;
      else if (char === quote) quote = null;
      continue;
    }
    if (comment) {
      if (comment === "line" && char === "\n") comment = null;
      else if (comment === "block" && char === "*" && next === "/") {
        comment = null;
        i++;
      }
      continue;
    }
    if (char === '"' || char === "'" || char === "`") {
      quote = char;
      continue;
    }
    if (char === "/" && next === "/") {
      comment = "line";
      i++;
      continue;
    }
    if (char === "/" && next === "*") {
      comment = "block";
      i++;
      continue;
    }
    if (char === "{" || char === "[") depth++;
    else if (char === "}" || char === "]") {
      depth--;
      if (depth === 0) return source.slice(openIndex, i + 1);
    }
  }
  return source.slice(openIndex);
}

/** Key-shaped string literals in value position inside a declaration
 * block. Denylisted property names and values that cannot be a catalog
 * leaf (class names, storage keys, env names) are dropped here rather
 * than being looked up and reported as missing. */
export function mapValues(block: string): string[] {
  const values: string[] = [];
  const valueRe =
    /(?:([A-Za-z0-9_$]+|"[^"\n]+"|'[^'\n]+')\s*:\s*)?["']([^"'\n]{1,80})["']/g;
  for (const match of block.matchAll(valueRe)) {
    const prop = match[1]?.replace(/['"]/g, "");
    if (prop && NON_KEY_PROPS.has(prop)) continue;
    if (!KEY_SHAPED.test(match[2])) continue;
    values.push(match[2]);
  }
  return values;
}

/** Every `*KEY*` constant initialised with an object/array literal. */
export function keyMapDeclarations(
  source: string,
): Array<{ name: string; values: string[] }> {
  const found: Array<{ name: string; values: string[] }> = [];
  for (const match of source.matchAll(DECL_RE)) {
    const open = match.index! + match[0].length - 1;
    const values = mapValues(blockAt(source, open));
    if (values.length > 0) found.push({ name: match[1], values });
  }
  return found;
}

/**
 * Does this constant look like a map of message keys, and if so which
 * namespace does it belong to?
 *
 * Classification is by content, not by name (review finding 4): a
 * constant is only judged against the catalog when most of its values
 * already resolve there. `QUERY_KEYS`, `STORAGE_KEYS` and friends carry
 * no catalog keys, score zero, and are ignored — they must not force
 * anyone to touch this file.
 *
 * `hits < values.length` on an otherwise-matching map is the interesting
 * case: something that walks and talks like a label map with one key
 * that does not exist. That is the bug this guard is for.
 */
export function classifyKeyMap(
  values: string[],
  namespaces: string[],
  catalog: Set<string>,
): { namespace: string; missing: string[] } | null {
  let best: { namespace: string; missing: string[] } | null = null;
  for (const namespace of namespaces) {
    const missing = values.filter((v) => !catalog.has(`${namespace}.${v}`));
    if (best === null || missing.length < best.missing.length) {
      best = { namespace, missing };
    }
  }
  if (best === null) return null;
  const hits = values.length - best.missing.length;
  // Needs a real majority and at least two hits: one accidental collision
  // with a catalog leaf is not evidence of anything.
  if (hits < 2 || hits * 2 <= values.length) return null;
  return best;
}

// --- assertions -------------------------------------------------------

describe("literal t() keys exist in the catalog", () => {
  const missing: string[] = [];
  let scanned = 0;
  for (const file of FILES) {
    for (const key of literalMessageKeys(readFileSync(file, "utf8"))) {
      scanned++;
      if (!EN.has(key)) missing.push(`${rel(file)} -> ${key}`);
    }
  }

  it("scans a plausible number of call sites", () => {
    // Tripwire: a broken regex must fail loudly, not pass vacuously.
    expect(scanned).toBeGreaterThan(1000);
  });

  it("finds no key that the catalog does not define", () => {
    expect(missing).toEqual([]);
  });
});

describe("message key maps", () => {
  const declarations = new Map<string, string[]>();
  for (const file of FILES) {
    for (const decl of keyMapDeclarations(readFileSync(file, "utf8"))) {
      declarations.set(`${rel(file)}::${decl.name}`, decl.values);
    }
  }

  it("resolves every registered map value against the catalog", () => {
    const missing: string[] = [];
    for (const [id, namespace] of Object.entries(MESSAGE_KEY_MAPS)) {
      for (const value of declarations.get(id) ?? []) {
        if (!EN.has(`${namespace}.${value}`)) {
          missing.push(`${id} -> ${namespace}.${value}`);
        }
      }
    }
    expect(missing).toEqual([]);
  });

  it("keeps the registry pointing at constants that still exist", () => {
    const stale = Object.keys(MESSAGE_KEY_MAPS).filter(
      (id) => !declarations.has(id),
    );
    expect(
      stale,
      "MESSAGE_KEY_MAPS names a constant this scan no longer finds — it was " +
        "renamed, moved or deleted. Update the entry (or drop it) so the " +
        "registered map keeps being checked",
    ).toEqual([]);
  });

  it("finds no unregistered constant that looks like a broken key map", () => {
    // Unregistered constants are classified by content: only the ones
    // whose values mostly resolve are judged, so an unrelated QUERY_KEYS
    // or STORAGE_KEYS on another branch cannot fail this.
    const suspicious: string[] = [];
    for (const [id, values] of declarations) {
      if (id in MESSAGE_KEY_MAPS) continue;
      const verdict = classifyKeyMap(values, NAMESPACES, EN);
      if (verdict && verdict.missing.length > 0) {
        suspicious.push(
          `${id} -> ${verdict.namespace}.{${verdict.missing.join(", ")}}`,
        );
      }
    }
    expect(
      suspicious,
      "these constants read as message-key maps but carry keys the catalog " +
        "does not define; fix the key, or register the map in " +
        "MESSAGE_KEY_MAPS if it is checked under a different namespace",
    ).toEqual([]);
  });
});

// --- the guard has to actually catch things ---------------------------

describe("scanner catches a violation", () => {
  it("resolves keys through the file's namespace", () => {
    const source = 'const t = useTranslations("assessments");\nt("statusDraft");';
    expect(literalMessageKeys(source)).toEqual(["assessments.statusDraft"]);
  });

  it("handles several bindings, root namespace and t.rich", () => {
    const source = [
      'const t = useTranslations("common");',
      'const tc = await getTranslations("recruitment");',
      'const tr = useTranslations();',
      't.rich("detail");',
      'tc("aiStageVerdict");',
      'tr("common.cancel");',
    ].join("\n");
    expect(literalMessageKeys(source).sort()).toEqual([
      "common.cancel",
      "common.detail",
      "recruitment.aiStageVerdict",
    ]);
  });

  it("would report a key that is not in the catalog", () => {
    const source = 'const t = useTranslations("assessments");\nt("noSuchKey");';
    const found = literalMessageKeys(source).filter((key) => !EN.has(key));
    expect(found).toEqual(["assessments.noSuchKey"]);
  });

  it("skips dynamic arguments instead of inventing keys", () => {
    const source = [
      'const t = useTranslations("assessments");',
      "t(labelKey);",
      "t(`status${code}`);",
      "t(ASSESSMENT_STATUS_KEYS[status]);",
    ].join("\n");
    expect(literalMessageKeys(source)).toEqual([]);
  });

  it("reads key-map values and drops non-key properties", () => {
    const source = [
      "const TYPE_OPTION_KEYS = [",
      '  { value: "self", labelKey: "typeSelf" },',
      "];",
      "const STATUS_LABEL_KEYS: Record<string, string> = {",
      '  draft: "statusDraft",',
      "};",
    ].join("\n");
    expect(keyMapDeclarations(source)).toEqual([
      { name: "TYPE_OPTION_KEYS", values: ["typeSelf"] },
      { name: "STATUS_LABEL_KEYS", values: ["statusDraft"] },
    ]);
  });

  it("reads a map whose type annotation spans several lines", () => {
    const source = [
      "const STALENESS_TEXT_KEYS: Record<",
      "  StalenessReason,",
      "  string",
      "> = {",
      '  stale: "aiStale",',
      "};",
    ].join("\n");
    expect(keyMapDeclarations(source)).toEqual([
      { name: "STALENESS_TEXT_KEYS", values: ["aiStale"] },
    ]);
  });

  it("ignores a *_KEY constant that is not a map", () => {
    expect(keyMapDeclarations('const DRAFT_KEY_PREFIX = "hrpulsar:draft:";')).toEqual(
      [],
    );
  });

  it("drops values that cannot be a catalog leaf", () => {
    // review finding 5: a class name next to a label key used to be
    // looked up as company.bg-red-500.
    const source = [
      "const STATUS_LABEL_KEYS = {",
      '  draft: "statusDraft",',
      '  className: "bg-red-500",',
      '  storage: "hrpulsar:draft:",',
      "};",
    ].join("\n");
    expect(keyMapDeclarations(source)).toEqual([
      { name: "STATUS_LABEL_KEYS", values: ["statusDraft"] },
    ]);
  });

  it("does not let a brace inside a string swallow the next declaration", () => {
    // review finding 5: the depth counter ignored quoting, so an
    // unbalanced brace in a value ran the block past its own closer and
    // pulled the following constant's keys in with it.
    const source = [
      "const A_KEYS = {",
      '  intro: "opening brace {",',
      '  draft: "statusDraft",',
      "};",
      "const LATER_KEYS = {",
      '  done: "statusDone",',
      "};",
    ].join("\n");
    expect(keyMapDeclarations(source)).toEqual([
      { name: "A_KEYS", values: ["statusDraft"] },
      { name: "LATER_KEYS", values: ["statusDone"] },
    ]);
  });

  it("ignores constants whose values are not catalog keys", () => {
    // review finding 4: another branch adding these must not fail CI.
    const catalog = new Set(["assessments.statusDraft", "assessments.statusDone"]);
    expect(
      classifyKeyMap(["employees", "positions"], ["assessments"], catalog),
    ).toBeNull();
    expect(classifyKeyMap(["statusDraft"], ["assessments"], catalog)).toBeNull();
  });

  it("reports a map that is mostly catalog keys but has a broken one", () => {
    const catalog = new Set([
      "assessments.statusDraft",
      "assessments.statusDone",
      "assessments.statusSent",
    ]);
    expect(
      classifyKeyMap(
        ["statusDraft", "statusDone", "statusSent", "statusRenamed"],
        ["assessments", "common"],
        catalog,
      ),
    ).toEqual({ namespace: "assessments", missing: ["statusRenamed"] });
  });

  it("picks the namespace that explains the most values", () => {
    const catalog = new Set(["common.cancel", "common.back", "other.cancel"]);
    expect(
      classifyKeyMap(["cancel", "back"], ["other", "common"], catalog),
    ).toEqual({ namespace: "common", missing: [] });
  });
});
