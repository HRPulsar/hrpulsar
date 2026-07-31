// HRP-491: permanent guard for the message catalogs. en.json and de.json
// must carry the same key set (a one-sided key renders raw on the other
// locale), every message must be valid ICU, and the ICU argument + rich-tag
// sets must match per key — a dropped/renamed {arg} or an extra <tag> in one
// locale throws at render time.
//
// HRP-482: arguments are extracted with the real ICU parser
// (@formatjs/icu-messageformat-parser — the same grammar next-intl renders
// with) instead of a regex: the old `[,}]`-anchored pattern mistook the
// first word of a one-word plural branch for an argument name, so a correct
// German translation could not pass.
//
// Version note: the direct devDependency (^3.5.15) currently resolves to
// the same node_modules entry as next-intl's transitive copy (via
// intl-messageformat), so "same grammar" holds literally. If a future
// next-intl bump splits the two across a major, re-align the pin.
import { parse, TYPE } from "@formatjs/icu-messageformat-parser";
import type { MessageFormatElement } from "@formatjs/icu-messageformat-parser";
import { describe, expect, it } from "vitest";

import deMessages from "../../messages/de.json";
import enMessages from "../../messages/en.json";

type Tree = { [key: string]: string | Tree };

function flatEntries(tree: Tree, prefix = ""): Array<[string, string]> {
  return Object.entries(tree).flatMap(([key, value]) =>
    typeof value === "string"
      ? [[`${prefix}${key}`, value] as [string, string]]
      : flatEntries(value, `${prefix}${key}.`),
  );
}

function collect(
  nodes: MessageFormatElement[],
  args: Set<string>,
  tags: Set<string>,
): void {
  for (const node of nodes) {
    switch (node.type) {
      case TYPE.argument:
        args.add(node.value);
        break;
      case TYPE.number:
      case TYPE.date:
      case TYPE.time:
        // A string style ("::currency/EUR", "short") changes what renders —
        // keep it in the signature so locales cannot silently diverge on it.
        args.add(
          typeof node.style === "string"
            ? `${node.value}:${node.style}`
            : node.value,
        );
        break;
      case TYPE.select:
      case TYPE.plural:
        args.add(node.value);
        for (const option of Object.values(node.options)) {
          collect(option.value, args, tags);
        }
        break;
      case TYPE.tag:
        tags.add(node.value);
        collect(node.children, args, tags);
        break;
      default:
        break;
    }
  }
}

// "count,name|b" — sorted ICU argument names, then sorted rich-text tag
// names. Tag parity matters too: a tag present only in one locale means the
// call site does not pass its render function there.
function icuSignature(value: string): string {
  const args = new Set<string>();
  const tags = new Set<string>();
  collect(parse(value), args, tags);
  return `${[...args].sort().join(",")}|${[...tags].sort().join(",")}`;
}

describe("i18n catalog parity (en/de)", () => {
  const en = new Map(flatEntries(enMessages as unknown as Tree));
  const de = new Map(flatEntries(deMessages as unknown as Tree));

  it("keeps the same key set in both catalogs", () => {
    const onlyEn = [...en.keys()].filter((k) => !de.has(k));
    const onlyDe = [...de.keys()].filter((k) => !en.has(k));
    expect(onlyEn).toEqual([]);
    expect(onlyDe).toEqual([]);
  });

  it("parses every message as valid ICU", () => {
    const invalid: string[] = [];
    for (const [locale, catalog] of [
      ["en", en],
      ["de", de],
    ] as const) {
      for (const [key, value] of catalog) {
        try {
          parse(value);
        } catch (error) {
          invalid.push(`${locale}:${key} — ${(error as Error).message}`);
        }
      }
    }
    expect(invalid).toEqual([]);
  });

  it("keeps ICU argument and rich-tag sets identical per key", () => {
    const mismatches: string[] = [];
    for (const [key, enValue] of en) {
      const deValue = de.get(key);
      if (deValue === undefined) continue; // covered by the parity test
      let enSig: string;
      let deSig: string;
      try {
        enSig = icuSignature(enValue);
        deSig = icuSignature(deValue);
      } catch {
        continue; // covered by the valid-ICU test
      }
      if (enSig !== deSig) {
        mismatches.push(`${key}: en[${enSig}] de[${deSig}]`);
      }
    }
    expect(mismatches).toEqual([]);
  });
});
