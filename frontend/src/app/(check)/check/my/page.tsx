import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { MyChecksRequestPage } from "@/components/public-check/saved-pages";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("publicCheck");
  return { title: t("myRequestTitle"), robots: { index: false, follow: false } };
}

export default function PublicCheckMyRequestRoute() {
  return <MyChecksRequestPage />;
}
