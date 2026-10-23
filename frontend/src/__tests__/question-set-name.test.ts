// HRP-1117: the Interview questions tabs and set titles read in the
// interface language - the set names the backend stores are labels.

import { readdirSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { questionSetName } from "../components/recruitment/question-set-name";

const MESSAGES_DIR = resolve(__dirname, "../../messages");
const CATALOGS: [string, { recruitment: Record<string, string> }][] =
  readdirSync(MESSAGES_DIR)
    .filter((file) => file.endsWith(".json"))
    .sort()
    .map((file) => [
      basename(file, ".json"),
      JSON.parse(readFileSync(resolve(MESSAGES_DIR, file), "utf8")),
    ]);

const QUESTION_SERVICE = readFileSync(
  resolve(__dirname, "../../../backend/app/modules/recruitment/question_service.py"),
  "utf8",
);

// Every name the backend writes on its own: `_round_label`,
// `_default_set_name` and the sample set.
const FIXED = [
  "Pre-interview",
  "Final",
  "Next round",
  "Regenerated set",
  "Final round",
  "Pre-interview set",
  "Sample set",
];
const STORED = [...FIXED, "Interview 2"];

const translator =
  (messages: Record<string, string>, locale: string) =>
  (key: string, values?: Record<string, string | number>) => {
    const raw = messages[key];
    expect(raw, `${locale}: ${key}`).toBeTruthy();
    return raw!.replace("{number}", String(values?.number ?? ""));
  };

describe("question set names (HRP-1117)", () => {
  it("covers every name the backend stores", () => {
    for (const name of FIXED) expect(QUESTION_SERVICE, name).toContain(`"${name}"`);
    expect(QUESTION_SERVICE).toContain('f"Interview {round_number}"');
  });

  for (const [locale, messages] of CATALOGS) {
    it(`reads each of them from the ${locale} catalog`, () => {
      const t = translator(messages.recruitment, locale);
      for (const name of STORED) {
        const label = questionSetName(t, name);
        if (locale === "en") expect(label).toBe(name);
        if (locale === "ru") expect(label, name).not.toBe(name);
      }
      expect(questionSetName(t, "Interview 2")).toContain("2");
      // A name the backend did not write stays as written.
      expect(questionSetName(t, "Panel with the CTO")).toBe("Panel with the CTO");
    });
  }
});
