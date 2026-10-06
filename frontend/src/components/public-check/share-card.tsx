/**
 * The share card of the public check (HRP-928), server-side: the picture a
 * link preview shows, and what the result page's metadata says.
 *
 * A result's card speaks the language of the check (en or de), whatever
 * language the crawler asks for: its own catalogs, not the request's.
 * The font is the one next/og ships - nothing is fetched to draw the card.
 */
import { ImageResponse } from "next/og";
import { createTranslator } from "next-intl";
import { getLocale } from "next-intl/server";

import { API_BASE } from "@/lib/api-base";
import {
  checkLocaleFor,
  stepCounts,
  type CheckLocale,
  type CheckRead,
} from "@/lib/api/public-check";
import { getBrandName } from "@/lib/brand";
import { midSentence, type GalleryProcess } from "@/lib/public-check-gallery";
import { publicCheckOrigin } from "@/lib/public-check-host";

export const CARD_SIZE = { width: 1200, height: 630 };

const CATALOGS = {
  en: () => import("../../../messages/en.json"),
  de: () => import("../../../messages/de.json"),
};

export async function cardTranslator(locale: CheckLocale) {
  const messages = (await CATALOGS[locale]()).default;
  return createTranslator({ locale, messages, namespace: "publicCheck" });
}

/** The card language of a request with no check behind it. */
export async function requestCardLocale(): Promise<CheckLocale> {
  return checkLocaleFor(await getLocale());
}

/** The check behind a token, or null: unknown, expired, the backend away.
 * ponytail: the SaaS image has a relative API base, so the server asks the
 * check host's own /api (Caddy routes it to the backend) - one hop through
 * the public address; an internal backend URL for the frontend container
 * if that ever matters. */
export async function fetchCheck(token: string): Promise<CheckRead | null> {
  const base = API_BASE.startsWith("http") ? API_BASE : `${publicCheckOrigin()}${API_BASE}`;
  try {
    const res = await fetch(`${base}/public-check/checks/${encodeURIComponent(token)}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    return res.ok ? ((await res.json()) as CheckRead) : null;
  } catch {
    return null;
  }
}

/** "AI takes N of my M steps" of a ready check with steps in scope; null
 * otherwise - the card and the metadata then speak for the service. */
export function readyCounts(check: CheckRead | null) {
  if (check?.status !== "ready" || !check.result) return null;
  const counts = stepCounts(check.result);
  return counts.total > 0 ? counts : null;
}

type Translator = Awaited<ReturnType<typeof cardTranslator>>;

function card(
  t: Translator,
  headline: string,
  process?: string,
  headers?: Record<string, string>,
) {
  const brand = `${t("serviceName")} · ${getBrandName()}`;
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: 80,
          background: "#ffffff",
          color: "#1a1f36",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 32 }}>
          <div style={{ fontSize: 76, lineHeight: 1.1, letterSpacing: -2 }}>{headline}</div>
          {process ? (
            <div style={{ fontSize: 40, lineHeight: 1.3, color: "#4a5068" }}>{process}</div>
          ) : null}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 18, fontSize: 32 }}>
          <div style={{ width: 22, height: 22, borderRadius: 11, background: "#0066FF" }} />
          <div style={{ display: "flex" }}>{brand}</div>
        </div>
      </div>
    ),
    { ...CARD_SIZE, headers },
  );
}

/** The card of the service itself: the input page, the gallery, and any
 * result that is not ready, expired or unknown. */
export async function serviceCard(locale: CheckLocale) {
  const t = await cardTranslator(locale);
  // Never cached: under a result's URL it stands in only until the check is
  // ready, and a cacheable response (a production image route may be served
  // public, immutable, for a year) would pin it there for good. Its language
  // follows the request, too.
  return card(t, t("inputTitle"), undefined, { "cache-control": "no-store" });
}

/** How long a ready result's card may be cached: 5 minutes. */
const RESULT_CARD_CACHE = "public, max-age=300";

/** The card of a ready result: the headline figure and the process. */
export async function resultCard(check: CheckRead) {
  const counts = readyCounts(check);
  if (!counts) return serviceCard(check.locale);
  const t = await cardTranslator(check.locale);
  // Briefly cached, not next/og's year-long immutable: the card names a
  // process the visitor may delete ("delete my data"), and a CDN must let
  // go of it soon after.
  return card(t, t("shareHeadline", counts), check.title, {
    "cache-control": RESULT_CARD_CACHE,
  });
}

/** The card of a gallery process (HRP-930): the question its page asks
 * and the engine's answer in steps. */
export async function galleryCard(process: GalleryProcess, locale: CheckLocale) {
  const t = await cardTranslator(locale);
  return card(
    t,
    t("galleryProcessTitle", { process: midSentence(process.title) }),
    t("galleryStepsLine", stepCounts(process.result)),
  );
}
