import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
  {
    // HRP-482: user-facing copy must come from the i18n catalogs — string
    // literals rendered by JSX (bare text children AND literal/template
    // strings in expression children, via noStrings) are a missed
    // translation. Props stay out of scope on purpose (ignoreProps: true):
    // checking them flags ~10k className/variant/testid values for a
    // handful of real strings — prop copy was translated in F2 and is
    // guarded by review. Punctuation/glyph-only strings are allowed below.
    // Intentional English surfaces carry a targeted eslint-disable with a
    // reason (e.g. global-error.tsx renders outside NextIntlClientProvider).
    // HRP-512: src/lib, src/hooks and src/context render JSX too
    // (turnstile gate, ws provider, ee hooks) — they were outside the
    // original scope and drifted back into English literals.
    files: [
      "src/app/**/*.tsx",
      "src/components/**/*.tsx",
      "src/lib/**/*.tsx",
      "src/hooks/**/*.tsx",
      "src/context/**/*.tsx",
    ],
    rules: {
      "react/jsx-no-literals": [
        "error",
        {
          noStrings: true,
          ignoreProps: true,
          allowedStrings: [
            // Punctuation / separators / glyphs — locale-neutral.
            "—",
            "–",
            "-",
            "·",
            "•",
            "●",
            "*",
            "%",
            "/",
            "(",
            ")",
            ":",
            ".",
            ",",
            "#",
            "…",
            "...",
            "✓",
            "✗",
            "✕",
            "×",
            "✎",
            "←",
            "→",
            "ⓘ",
            "(i)",
            "⚡",
            "💡",
            "Δ",
            "·✓",
            "(~",
            "“",
            "”",
            "&ldquo;",
            "&rdquo;",
            "&middot;",
            "⌘K",
            // Units / counters — not translated.
            "v",
            "h",
            "KB)",
            "MB/s",
            "/ 2000",
            "---",
            // Verbatim tokens: ISO currency codes, brand/format names,
            // Manager/AI score abbreviations.
            "USD",
            "EUR",
            "GBP",
            "RUB",
            "LinkedIn",
            "XLSX",
            "M:",
            "AI:",
            "M&nbsp;",
            "AI&nbsp;",
          ],
        },
      ],
    },
  },
]);

export default eslintConfig;
