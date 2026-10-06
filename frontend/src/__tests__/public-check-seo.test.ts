// HRP-928/930: what search engines and link previews read of the public
// check. The check host gets its own robots.txt and sitemap and indexable
// input and gallery pages; the app host stays closed as before. A result is
// never indexed, and its preview speaks like its card - the figure once the
// check is ready, in the check's language.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let host = "check.hrpulsar.com";

vi.mock("next/headers", () => ({
  headers: async () => new Headers({ host }),
}));
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));
vi.mock("next-intl/server", async () => {
  const { createTranslator } = await import("next-intl");
  const messages = (await import("../../messages/en.json")).default;
  return {
    getLocale: async () => "en",
    getTranslations: async (namespace: string) =>
      createTranslator({ locale: "en", messages, namespace: namespace as "publicCheck" }),
  };
});

const { default: robots } = await import("@/app/robots");
const { default: sitemap } = await import("@/app/sitemap");
const inputPage = await import("@/app/(check)/check/page");
const resultPage = await import("@/app/(check)/check/r/[token]/page");
const { GALLERY } = await import("@/lib/public-check-gallery");

const fetchMock = vi.fn();

beforeEach(() => {
  host = "check.hrpulsar.com";
  vi.stubEnv("PUBLIC_CHECK_ENABLED", "true");
  vi.stubEnv("PUBLIC_CHECK_HOST", "check.hrpulsar.com");
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("robots.txt", () => {
  it("lets crawlers in on the check host and names its sitemap", async () => {
    expect(await robots()).toEqual({
      rules: { userAgent: "*", allow: "/" },
      sitemap: "https://check.hrpulsar.com/sitemap.xml",
    });
  });

  it("keeps the app host closed", async () => {
    host = "app.hrpulsar.com";
    expect(await robots()).toEqual({ rules: { userAgent: "*", disallow: "/" } });
  });

  it("keeps every host closed while the service is off", async () => {
    vi.stubEnv("PUBLIC_CHECK_ENABLED", "");
    expect(await robots()).toEqual({ rules: { userAgent: "*", disallow: "/" } });
  });
});

describe("sitemap.xml", () => {
  it("lists the input page, the gallery and every process on the check host", async () => {
    host = "check.hrpulsar.com:443";
    const urls = (await sitemap()).map((entry) => entry.url);
    expect(urls.slice(0, 2)).toEqual(["https://check.hrpulsar.com/", "https://check.hrpulsar.com/gallery"]);
    expect(urls).toHaveLength(2 + GALLERY.length);
    expect(urls).toHaveLength(37);
    expect(urls).toContain("https://check.hrpulsar.com/gallery/month-end-close");
    expect(urls.some((url) => url.includes("/r/"))).toBe(false);
  });

  it("does not exist on the app host", async () => {
    host = "app.hrpulsar.com";
    await expect(sitemap()).rejects.toThrow("NEXT_NOT_FOUND");
  });
});

describe("the links of the check pages", () => {
  it("follow the host the request came to", async () => {
    const { checkLinks } = await import("@/components/public-check/links");
    expect(await checkLinks()).toMatchObject({ inputHref: "/", galleryHref: "/gallery", myHref: "/my" });
    host = "app.hrpulsar.com";
    expect(await checkLinks()).toMatchObject({
      inputHref: "/check",
      galleryHref: "/check/gallery",
      myHref: "/check/my",
    });
  });
});

describe("the input page's preview", () => {
  it("is the service's own card, indexable on the check host only", async () => {
    const meta = await inputPage.generateMetadata();
    expect(meta.alternates?.canonical).toBe("https://check.hrpulsar.com/");
    expect(meta.metadataBase?.toString()).toBe("https://check.hrpulsar.com/");
    expect(meta.openGraph).toMatchObject({
      url: "https://check.hrpulsar.com/",
      title: "AI or Human? Check what AI can take from your process",
    });
    expect(meta.twitter).toMatchObject({ card: "summary_large_image" });
    expect(meta.robots).toEqual({ index: true, follow: true });

    host = "app.hrpulsar.com";
    expect((await inputPage.generateMetadata()).robots).toEqual({ index: false, follow: false });
  });
});

describe("a result's preview", () => {
  const params = Promise.resolve({ token: "tok-1" });

  function check(over: object = {}) {
    const step = (position: number) => ({ position, title: `Step ${position}` });
    return {
      status: "ready",
      locale: "en",
      title: "Month-end close",
      result: {
        buckets: { moves: [step(1), step(2)], to_review: [step(3)], stays: [] },
        out_of_scope: [step(4)],
      },
      ...over,
    };
  }

  function answer(body: object | null, status = 200) {
    fetchMock.mockResolvedValue({ ok: status === 200, status, json: async () => body });
  }

  it("carries the figure and the process once the check is ready - and is never indexed", async () => {
    answer(check());
    const meta = await resultPage.generateMetadata({ params });
    // The relative API base of the SaaS image reaches the backend through
    // the check host; an absolute one (dev, self-hosted) is used as is.
    expect(fetchMock.mock.calls[0][0]).toMatch(/^https?:\/\/[^/]+\/api\/public-check\/checks\/tok-1$/);
    expect(meta.title).toBe("AI takes 2 of my 3 steps in “Month-end close”");
    expect(meta.openGraph).toMatchObject({
      url: "https://check.hrpulsar.com/r/tok-1",
      title: "AI takes 2 of my 3 steps in “Month-end close”",
    });
    expect(meta.twitter).toMatchObject({ card: "summary_large_image" });
    expect(meta.robots).toEqual({ index: false, follow: false });
  });

  it("speaks the check's language, not the crawler's", async () => {
    answer(check({ locale: "de", title: "Wareneingang" }));
    const meta = await resultPage.generateMetadata({ params });
    expect(meta.title).toBe("KI übernimmt 2 von meinen 3 Schritten bei „Wareneingang“");
  });

  it("is shared by its check-host address even from the app host", async () => {
    host = "app.hrpulsar.com";
    const page = await resultPage.default({ params });
    expect(page.props.shareUrl).toBe("https://check.hrpulsar.com/r/tok-1");
  });

  it.each([
    ["still running", () => answer(check({ status: "running", result: null }))],
    ["unknown or expired", () => answer({ detail: "not found" }, 404)],
    ["the backend away", () => fetchMock.mockRejectedValue(new TypeError("fetch failed"))],
  ])("speaks for the service when the check is %s", async (_label, arrange) => {
    arrange();
    const meta = await resultPage.generateMetadata({ params });
    expect(meta.title).toBe("AI or Human? Process breakdown");
    expect(meta.alternates?.canonical).toBe("https://check.hrpulsar.com/r/tok-1");
  });
});
