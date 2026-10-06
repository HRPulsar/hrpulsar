import type { Metadata } from "next";
import { headers } from "next/headers";

import { getBrandName } from "@/lib/brand";
import {
  appOrigin,
  isPublicCheckRequest,
  publicCheckOrigin,
} from "@/lib/public-check-host";

/** UTM of the bridge into the product (HRP-925): the signup funnel sees
 * which visitors came from the public check. */
const REGISTER_UTM =
  "utm_source=public_check&utm_medium=result&utm_campaign=ai_or_human";
/** The same for "move to HRPulsar" on "my checks" (HRP-927). */
const MOVE_UTM =
  "utm_source=public_check&utm_medium=my_checks&utm_campaign=ai_or_human";

export interface CheckLinks {
  /** The input page: "/" on the check host, "/check" on the app host. */
  inputHref: string;
  /** A result is `${resultBase}/<token>`. */
  resultBase: string;
  /** The gallery (HRP-930); a process is `${galleryHref}/<slug>`. */
  galleryHref: string;
  /** Registration on the app host, with the UTM of the check. */
  registerHref: string;
  /** "My checks" (HRP-926): `${myHref}/<link>` lists the saved checks. */
  myHref: string;
  /** "Move to HRPulsar" (HRP-927) for an address without an account:
   * registration on the app host, the address goes in `&email=`. */
  moveRegisterHref: string;
  /** The same for an address with an account: the page of the app host
   * that moves the checks, the "my checks" link goes in `#link=` (a bearer
   * token: the fragment never reaches a server or a Referer). */
  moveImportHref: string;
}

/** Did this request come to the check host, not to /check on the app host? */
export async function onCheckHost(): Promise<boolean> {
  const hdrs = await headers();
  return isPublicCheckRequest(hdrs.get("x-forwarded-host") || hdrs.get("host"));
}

/** Links of the check pages for the host this request came to. */
export async function checkLinks(): Promise<CheckLinks> {
  const onCheck = await onCheckHost();
  return {
    inputHref: onCheck ? "/" : "/check",
    resultBase: onCheck ? "/r" : "/check/r",
    galleryHref: onCheck ? "/gallery" : "/check/gallery",
    registerHref: `${appOrigin()}/register?${REGISTER_UTM}`,
    myHref: onCheck ? "/my" : "/check/my",
    moveRegisterHref: `${appOrigin()}/register?${MOVE_UTM}`,
    moveImportHref: `${appOrigin()}/coverage/saved-checks`,
  };
}

/**
 * Metadata of a check page (HRP-928/930): its own link preview instead of
 * the product's, canonical on the check host. `path` is the page's path
 * there ("/", "/r/<token>", "/gallery/<slug>"). `index` - may search
 * engines index it: only ever on the check host (the app host stays
 * closed), and never a result, which is somebody's own check.
 */
export async function checkPageMetadata({
  title,
  description,
  path,
  index,
}: {
  title: string;
  description: string;
  path: string;
  index: boolean;
}): Promise<Metadata> {
  const origin = publicCheckOrigin();
  if (!origin) return {}; // the service is off: the layout answers 404
  const url = `${origin}${path}`;
  const indexable = index && (await onCheckHost());
  return {
    // The cards (opengraph-image) of the check resolve on its host.
    metadataBase: new URL(origin),
    title,
    description,
    alternates: { canonical: url },
    openGraph: { type: "website", siteName: getBrandName(), url, title, description },
    twitter: { card: "summary_large_image", title, description },
    robots: { index: indexable, follow: indexable },
  };
}
