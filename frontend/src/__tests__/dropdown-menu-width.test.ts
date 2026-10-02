// HRP-837 — action and kebab menus clipped long commands because the
// popup took the trigger's width (`--anchor-width`), which for a kebab
// icon is ~28px, floored at 8rem. The shared content now grows with its
// longest item and wraps by words only past a sane maximum, so every menu
// in the system is fixed by this one file.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = readFileSync(
  resolve(__dirname, "../components/ui/dropdown-menu.tsx"),
  "utf8",
);

describe("dropdown menu width (HRP-837)", () => {
  it("is sized by its content, with the trigger width only as a floor", () => {
    expect(SRC).toContain("w-max");
    expect(SRC).toContain("min-w-[max(8rem,var(--anchor-width))]");
    expect(SRC).not.toContain("w-(--anchor-width)");
  });

  it("wraps by words past a maximum instead of clipping", () => {
    expect(SRC).toContain("max-w-[min(24rem,var(--available-width))]");
    expect(SRC).not.toMatch(/DropdownMenuContent[\s\S]*?whitespace-nowrap[\s\S]*?DropdownMenuGroup/);
  });
});
