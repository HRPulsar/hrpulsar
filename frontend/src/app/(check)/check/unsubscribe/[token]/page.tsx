import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { UnsubscribePage } from "@/components/public-check/saved-pages";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("publicCheck");
  return { title: t("unsubscribeTitle"), robots: { index: false, follow: false } };
}

export default async function PublicCheckUnsubscribeRoute({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <UnsubscribePage token={token} />;
}
