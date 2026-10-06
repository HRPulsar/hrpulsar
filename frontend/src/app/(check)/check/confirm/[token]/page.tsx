import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { checkLinks } from "@/components/public-check/links";
import { ConfirmEmailPage } from "@/components/public-check/saved-pages";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("publicCheck");
  // A letter's link: never in a search index.
  return { title: t("confirmTitle"), robots: { index: false, follow: false } };
}

export default async function PublicCheckConfirmRoute({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  const links = await checkLinks();
  return <ConfirmEmailPage token={token} myHref={links.myHref} />;
}
