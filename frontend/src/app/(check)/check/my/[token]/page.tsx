import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { checkLinks } from "@/components/public-check/links";
import { SavedChecksPage } from "@/components/public-check/saved-pages";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("publicCheck");
  return { title: t("myTitle"), robots: { index: false, follow: false } };
}

export default async function PublicCheckMyRoute({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  const links = await checkLinks();
  return (
    <SavedChecksPage
      key={token}
      token={token}
      myHref={links.myHref}
      inputHref={links.inputHref}
      moveRegisterHref={links.moveRegisterHref}
      moveImportHref={links.moveImportHref}
    />
  );
}
