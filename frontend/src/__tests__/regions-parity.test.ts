// HRP-1066: the company Region select offers REGIONS, and the backend
// rejects any code outside its own REGIONS with `unsupported_region`. The
// two lists are copies; this guard parses the Python one and compares.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { REGIONS } from "@/lib/regions";

describe("company regions", () => {
  it("frontend REGIONS matches backend REGIONS", () => {
    const source = readFileSync(
      resolve(__dirname, "../../../backend/app/modules/company/schemas.py"),
      "utf8",
    );
    const start = source.indexOf("REGIONS = frozenset(");
    expect(start, "REGIONS not found in company/schemas.py").toBeGreaterThan(-1);
    const block = source.slice(start, source.indexOf(".split()", start));
    const python = block.match(/\b[A-Z]{2}\b/g) ?? [];

    expect(python).toHaveLength(249);
    expect([...REGIONS].sort()).toEqual([...python].sort());
    expect(new Set(REGIONS).size).toBe(REGIONS.length);
  });

  it("every code has a country name in Intl", () => {
    const names = new Intl.DisplayNames(["en"], { type: "region" });
    for (const code of REGIONS) expect(names.of(code), code).not.toBe(code);
  });
});
