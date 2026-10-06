// @vitest-environment jsdom
//
// HRP-930: the gallery of the public check - the 35 public processes of the
// expert library as check results without hours (`shares` null). The list groups
// them by domain and searches their names; a process page shows the result
// view of a check, with no hour figure anywhere, and sends the visitor to
// check a process of their own.

import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { NextIntlClientProvider, createTranslator } from "next-intl";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import { stepCounts } from "@/lib/api/public-check";
import { GALLERY, galleryProcess, midSentence } from "@/lib/public-check-gallery";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: enMessages, namespace: namespace as "publicCheck" }),
}));
vi.mock("@/components/public-check/links", () => ({
  checkLinks: async () => ({
    inputHref: "/",
    resultBase: "/r",
    galleryHref: "/gallery",
    registerHref: "https://app.hrpulsar.com/register",
  }),
  checkPageMetadata: async (args: object) => args,
}));

const { default: GalleryPage } = await import("@/app/(check)/check/gallery/page");
const ProcessPage = await import("@/app/(check)/check/gallery/[slug]/page");

const t = enMessages.publicCheck as Record<string, string>;

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const byId = (id: string) => container.querySelector<HTMLElement>(`[data-testid="${id}"]`);
const allById = (prefix: string) =>
  [...container.querySelectorAll<HTMLElement>(`[data-testid^="${prefix}"]`)].map(
    (el) => el.dataset.testid,
  );

async function render(node: ReactNode) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages} timeZone="UTC">
        {node}
      </NextIntlClientProvider>,
    );
  });
}

describe("the gallery data", () => {
  it("holds the 35 public processes, each a result without hours", () => {
    expect(GALLERY).toHaveLength(35);
    // HRPulsar's own processes are the library's calibration set, never a page.
    expect(GALLERY.filter((p) => p.industry === "internal")).toEqual([]);
    for (const process of GALLERY) {
      expect(process.result.shares).toBeNull();
      expect(process.result.hours.total).toBe(0);
      expect(stepCounts(process.result).total).toBeGreaterThan(0);
    }
  });

  it("has a label for every domain and source kind in every catalog", () => {
    // Discovered, not imported by name: a community checkout has no ru.json.
    const dir = resolve(__dirname, "../../messages");
    const domains = new Set(GALLERY.map((p) => p.domain));
    const kinds = new Set(GALLERY.flatMap((p) => p.sources.map((s) => s.kind)));
    for (const file of readdirSync(dir).filter((f) => f.endsWith(".json"))) {
      const catalog = JSON.parse(readFileSync(resolve(dir, file), "utf-8")).publicCheck;
      for (const domain of domains) expect(catalog[`galleryDomain_${domain}`], `${file} ${domain}`).toBeTruthy();
      for (const kind of kinds) expect(catalog[`galleryKind_${kind}`], `${file} ${kind}`).toBeTruthy();
    }
  });

  it("puts a title mid-sentence without breaking its acronyms", () => {
    expect(midSentence("Month-end close")).toBe("month-end close");
    expect(midSentence("KYC/CDD at account opening")).toBe("KYC/CDD at account opening");
    expect(midSentence("UI concept")).toBe("UI concept");
  });
});

describe("the gallery page", () => {
  it("lists every process by domain, each with its steps that go to an agent", async () => {
    await render(await GalleryPage());

    expect(allById("check-gallery-item-")).toHaveLength(35);
    const domains = allById("check-gallery-domain-");
    expect(domains).toHaveLength(new Set(GALLERY.map((p) => p.domain)).size);
    const finance = byId("check-gallery-domain-finance")!;
    expect(finance.querySelector("h2")!.textContent).toBe(t.galleryDomain_finance);
    const close = byId("check-gallery-item-month-end-close")!;
    expect(close.getAttribute("href")).toBe("/gallery/month-end-close");
    const { moves, total } = stepCounts(galleryProcess("month-end-close")!.result);
    expect(close.textContent).toContain(`${moves} of ${total} steps`);
    expect(byId("check-gallery-cta")!.getAttribute("href")).toBe("/");
  });

  it("searches the names without a library, and says when nothing matches", async () => {
    await render(await GalleryPage());
    const search = byId("check-gallery-search") as HTMLInputElement;
    const type = async (value: string) => {
      await act(async () => {
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
        setter.call(search, value);
        search.dispatchEvent(new Event("input", { bubbles: true }));
      });
    };

    await type("ONBOARD");
    expect(allById("check-gallery-item-")).toEqual(["check-gallery-item-employee-onboarding"]);
    expect(allById("check-gallery-domain-")).toEqual(["check-gallery-domain-hr"]);
    expect(byId("check-gallery-empty")).toBeNull();

    await type("no such process");
    expect(allById("check-gallery-item-")).toHaveLength(0);
    expect(byId("check-gallery-empty")!.textContent).toBe(t.galleryEmpty);
  });
});

describe("a gallery process page", () => {
  const slug = "month-end-close";
  const process = galleryProcess(slug)!;
  const params = Promise.resolve({ slug });

  it("asks the question of the process and answers in steps, in the result view of a check", async () => {
    await render(await ProcessPage.default({ params }));

    expect(container.querySelector("h1")!.textContent).toBe("Can AI do month-end close?");
    const { moves, total } = stepCounts(process.result);
    expect(byId("check-gallery-steps")!.textContent).toBe(
      `${moves} of ${total} steps ${moves === 1 ? "goes" : "go"} to an agent`,
    );
    // The lists of the result page, every step with its reason.
    for (const [bucket, testId] of [
      ["moves", "check-list-moves"],
      ["to_review", "check-list-to-review"],
      ["stays", "check-list-stays"],
    ] as const) {
      for (const step of process.result.buckets[bucket]) {
        expect(byId(testId)!.querySelector(`[data-testid="check-step-${step.position}"]`)).not.toBeNull();
      }
    }
    // No hours anywhere: no percent, no figures, no "no estimate" per step.
    expect(byId("check-result-headline")).toBeNull();
    expect(byId("check-result-no-shares")).toBeNull();
    expect(byId("check-result-figures")).toBeNull();
    expect(byId("check-result-unestimated")).toBeNull();
    expect(container.textContent).not.toContain("%");
    expect(container.textContent).not.toContain(t.stepNoEstimate);

    expect(byId("check-gallery-back")!.getAttribute("href")).toBe("/gallery");
    expect(byId("check-gallery-cta")!.getAttribute("href")).toBe("/");
    expect(byId("check-gallery-cta")!.textContent).toBe(t.galleryCta);
    const sources = byId("check-gallery-sources")!;
    for (const source of process.sources) {
      expect(sources.querySelector(`a[href="${source.url}"]`)).not.toBeNull();
    }
  });

  it("is indexable, with the question as its title", async () => {
    const meta = (await ProcessPage.generateMetadata({ params })) as Record<string, unknown>;
    expect(meta).toMatchObject({
      title: `Can AI do ${midSentence(process.title)}?`,
      path: `/gallery/${slug}`,
      index: true,
    });
  });

  it("is a 404 for a slug the gallery does not have", async () => {
    await expect(
      ProcessPage.default({ params: Promise.resolve({ slug: "no-such-process" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
  });
});

describe("the gallery list's order", () => {
  it("sorts the domains by the interface locale, as the server does", async () => {
    // Review 2.2 D4: a bare localeCompare sorts by the runtime's locale -
    // the server's and the browser's differ, and hydration breaks.
    const { GalleryList } = await import("@/components/public-check/gallery-list");
    const compare = vi.spyOn(String.prototype, "localeCompare");
    const item = (slug: string, domain: string) => ({ slug, title: slug, domain, moves: 1, total: 2 });
    await act(async () => {
      root.render(
        <NextIntlClientProvider locale="de" messages={enMessages} timeZone="UTC">
          <GalleryList items={[item("a", "strategy"), item("b", "management")]} href="/gallery" />
        </NextIntlClientProvider>,
      );
    });
    expect(compare).toHaveBeenCalled();
    for (const call of compare.mock.calls) expect(call[1]).toBe("de");
    compare.mockRestore();
  });
});
