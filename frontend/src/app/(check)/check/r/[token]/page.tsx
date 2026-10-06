import type { Metadata } from "next";

import { CheckResultPage } from "@/components/public-check/check-result";
import { checkLinks, checkPageMetadata } from "@/components/public-check/links";
import {
  cardTranslator,
  fetchCheck,
  readyCounts,
  requestCardLocale,
} from "@/components/public-check/share-card";
import { canonicalResultUrl } from "@/lib/public-check-host";

interface Props {
  params: Promise<{ token: string }>;
}

/** The link preview of a result (HRP-928) speaks like its card - in the
 * check's language, with the figure once it is ready. Never indexed. */
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { token } = await params;
  const check = await fetchCheck(token);
  const counts = readyCounts(check);
  const t = await cardTranslator(check?.locale ?? (await requestCardLocale()));
  return checkPageMetadata({
    title:
      check && counts
        ? t("shareTitle", { headline: t("shareHeadline", counts), process: check.title })
        : t("resultMetaTitle"),
    description: t("metaDescription"),
    path: `/r/${encodeURIComponent(token)}`,
    index: false,
  });
}

export default async function PublicCheckResultRoute({ params }: Props) {
  const { token } = await params;
  const links = await checkLinks();
  return (
    // Keyed by token: "try again" navigates to a new check, whose state
    // must not start from the failed one.
    <CheckResultPage
      key={token}
      token={token}
      inputHref={links.inputHref}
      resultBase={links.resultBase}
      registerHref={links.registerHref}
      shareUrl={canonicalResultUrl(token)}
    />
  );
}
