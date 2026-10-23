// @vitest-environment jsdom
//
// HRP-823…826 (QA 13.10): the tabs of the four section lists. `?tab=`
// opens a tab the caller sees and falls back to the first visible one
// otherwise (a `view` caller following a link to the manage tab); a click
// replaces the URL with the tab alone; "To do (N)" shows the backend's count.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

const { nav, getSpy } = vi.hoisted(() => ({
  nav: { search: "", replace: vi.fn() },
  getSpy: vi.fn((url: string) => Promise.resolve({ url, count: 4 })),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  usePathname: () => "/exams",
  useSearchParams: () => new URLSearchParams(nav.search),
}));

vi.mock("@/lib/api", () => ({ api: { get: (url: string) => getSpy(url) } }));

const { SectionTabs, useSectionTab, useTodoCount } = await import("@/components/section-tabs");

function Probe({ ids }: { ids: string[] }) {
  const tab = useSectionTab(ids);
  const todo = useTodoCount("/exams/todo-count", tab);
  return (
    <SectionTabs
      testIdPrefix="probe"
      active={tab}
      tabs={ids.map((id) => ({ id, label: id === "todo" ? todo.label : id }))}
    />
  );
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  nav.replace.mockClear();
  getSpy.mockClear();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render(search: string, ids: string[]) {
  nav.search = search;
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <Probe ids={ids} />
      </NextIntlClientProvider>,
    );
  });
}

const selected = () =>
  container.querySelector('[role="tab"][aria-selected="true"]')?.getAttribute("data-testid");

describe("SectionTabs (HRP-823…826)", () => {
  it("opens the tab the link names when the caller sees it", async () => {
    await render("tab=todo", ["all", "mine", "todo"]);
    expect(selected()).toBe("probe-tab-todo");
  });

  it("falls back to the first visible tab otherwise, and the URL follows", async () => {
    await render("tab=all&status=done", ["mine", "todo"]);
    expect(selected()).toBe("probe-tab-mine");
    expect(nav.replace).toHaveBeenCalledWith("/exams?tab=mine&status=done", { scroll: false });
  });

  it("leaves a URL without a tab as it is", async () => {
    await render("", ["all", "mine", "todo"]);
    expect(selected()).toBe("probe-tab-all");
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("puts the backend's count into the To do label", async () => {
    await render("", ["mine", "todo"]);
    expect(getSpy).toHaveBeenCalledWith("/exams/todo-count");
    expect(container.querySelector('[data-testid="probe-tab-todo"]')?.textContent).toBe("To do (4)");
  });

  it("switches by replacing the URL with the tab alone", async () => {
    await render("tab=mine&status=done", ["mine", "todo"]);
    await act(async () => {
      (container.querySelector('[data-testid="probe-tab-todo"]') as HTMLElement).click();
    });
    expect(nav.replace).toHaveBeenCalledWith("/exams?tab=todo", { scroll: false });
  });
});

describe("the four section lists share it", () => {
  const page = (name: string) =>
    readFileSync(resolve(__dirname, `../app/(dashboard)/${name}/page.tsx`), "utf8");

  it.each([
    ["exams", "exams", '["all", "mine", "todo"] : ["mine", "todo"]'],
    ["assessments", "assessments", '["all", "mine", "todo"] : ["mine", "todo"]'],
    ["development", "development", '["all", "mine", "todo"] : ["mine", "todo"]'],
    ["talent-market", "talent-market", '["all", "mine", "appointed"] : ["mine", "appointed"]'],
  ])("%s shows its manage tab only at manage", (name, section, ids) => {
    const src = page(name);
    expect(src).toContain(`const manage = canManageSection("${section}");`);
    expect(src).toContain(`useSectionTab(manage ? ${ids})`);
    expect(src).toContain("<SectionTabs");
  });

  it.each(["assessments", "development"])("%s mirrors the resolved tab, not the raw param", (name) => {
    const src = page(name);
    expect(src).toContain('if (searchParams.has("tab")) params.set("tab", tab);');
    expect(src).not.toContain('searchParams.get("tab")');
  });
});
