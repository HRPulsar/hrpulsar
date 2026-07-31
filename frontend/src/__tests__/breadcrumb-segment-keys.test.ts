// HRP-482: breadcrumb completeness guard. The dashboard header builds
// breadcrumbs from URL segments via SEGMENT_KEYS (header.tsx) — a route
// directory added without a map entry falls back to prettified English
// ("audit-log" → "Audit Log") and silently skips translation. Every static
// segment under src/app/(dashboard) must have a SEGMENT_KEYS entry, and
// every mapped key must exist in the sidebar namespace (de parity is
// covered by i18n-catalog-parity.test.ts). The platform tree ships its own
// header and is deliberately out of scope.
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import enMessages from "../../messages/en.json";

const FRONTEND = path.resolve(__dirname, "../..");
const DASHBOARD_APP = path.join(FRONTEND, "src", "app", "(dashboard)");
const HEADER = path.join(FRONTEND, "src", "components", "header.tsx");

// Route directories excluded from the public-repo sync (scripts/
// sync_repos.sh) whose SEGMENT_KEYS entries must survive there anyway —
// the stale check skips them, the mapped/dangling checks still cover them.
const ENTERPRISE_ONLY_SEGMENTS = new Set(["billing"]);

function collectStaticSegments(dir: string, acc: Set<string>): Set<string> {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const name = entry.name;
    const full = path.join(dir, name);
    if (name.startsWith("_")) continue; // private folder — not a URL segment
    if (name.startsWith("(") || name.startsWith("[")) {
      // Route groups vanish from the URL; dynamic segments render as
      // tCommon("detail") (UUID_RE) — recurse for their static children.
      collectStaticSegments(full, acc);
      continue;
    }
    acc.add(name);
    collectStaticSegments(full, acc);
  }
  return acc;
}

function segmentKeysFromHeaderSource(): Record<string, string> {
  const source = fs.readFileSync(HEADER, "utf8");
  const block = source.match(
    /const SEGMENT_KEYS: Record<string, string> = \{([\s\S]*?)\n\};/,
  );
  if (!block) {
    throw new Error(
      "SEGMENT_KEYS object not found in header.tsx — update this test's " +
        "extraction if the map moved or was renamed",
    );
  }
  const map: Record<string, string> = {};
  for (const entry of block[1].matchAll(
    /["']?([\w-]+)["']?\s*:\s*"(\w+)"/g,
  )) {
    map[entry[1]] = entry[2];
  }
  // Guard the extraction itself: an entry the value-regex cannot parse
  // (dotted key, single quotes) must fail loudly here, not surface later
  // as a confusing "unmapped segment".
  const entryLines = block[1]
    .split("\n")
    .filter((line) => line.includes(":")).length;
  if (Object.keys(map).length === 0 || Object.keys(map).length !== entryLines) {
    throw new Error(
      `SEGMENT_KEYS extraction parsed ${Object.keys(map).length} of ` +
        `${entryLines} entries — update the regex in this test`,
    );
  }
  return map;
}

describe("breadcrumb SEGMENT_KEYS completeness", () => {
  const segments = collectStaticSegments(DASHBOARD_APP, new Set<string>());
  const segmentKeys = segmentKeysFromHeaderSource();
  const sidebar = (enMessages as { sidebar: Record<string, unknown> }).sidebar;

  it("maps every static (dashboard) route segment", () => {
    const unmapped = [...segments].filter((s) => !(s in segmentKeys)).sort();
    expect(unmapped, "add these segments to SEGMENT_KEYS in header.tsx").toEqual(
      [],
    );
  });

  it("points every mapped segment at an existing sidebar.* key", () => {
    const dangling = Object.entries(segmentKeys)
      .filter(([, key]) => !(key in sidebar))
      .sort();
    expect(
      dangling,
      "add these keys to the sidebar namespace in messages/en.json + de.json",
    ).toEqual([]);
  });

  it("carries no stale entries for segments that no longer exist", () => {
    const stale = Object.keys(segmentKeys)
      .filter((s) => !segments.has(s) && !ENTERPRISE_ONLY_SEGMENTS.has(s))
      .sort();
    expect(stale, "remove these from SEGMENT_KEYS in header.tsx").toEqual([]);
  });
});
