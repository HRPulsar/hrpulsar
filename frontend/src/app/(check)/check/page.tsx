import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { CheckForm } from "@/components/public-check/check-form";
import { checkLinks, checkPageMetadata } from "@/components/public-check/links";
import { utmFrom } from "@/lib/api/public-check";
import { GALLERY } from "@/lib/public-check-gallery";

type SearchParams = Record<string, string | string[] | undefined>;

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("publicCheck");
  return checkPageMetadata({
    title: t("metaTitle"),
    description: t("metaDescription"),
    path: "/",
    index: true,
  });
}

export default async function PublicCheckInputPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const links = await checkLinks();
  const t = await getTranslations("publicCheck");
  return (
    <div className="space-y-8">
      <CheckForm resultBase={links.resultBase} utm={utmFrom(await searchParams)} />
      <p className="border-t pt-6 text-sm">
        <Link
          href={links.galleryHref}
          className="text-primary hover:underline"
          data-testid="check-link-gallery"
        >
          {t("galleryLink", { count: GALLERY.length })}
        </Link>
      </p>
    </div>
  );
}
