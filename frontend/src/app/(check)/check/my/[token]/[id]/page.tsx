import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { checkLinks } from "@/components/public-check/links";
import { SavedResultPage } from "@/components/public-check/saved-pages";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("publicCheck");
  return { title: t("resultMetaTitle"), robots: { index: false, follow: false } };
}

export default async function PublicCheckSavedResultRoute({
  params,
}: {
  params: Promise<{ token: string; id: string }>;
}) {
  const { token, id } = await params;
  const links = await checkLinks();
  return (
    <SavedResultPage
      key={`${token}/${id}`}
      token={token}
      id={id}
      myHref={links.myHref}
      inputHref={links.inputHref}
      registerHref={links.registerHref}
    />
  );
}
