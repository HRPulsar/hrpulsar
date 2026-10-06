import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { GalleryList } from "@/components/public-check/gallery-list";
import { checkLinks, checkPageMetadata } from "@/components/public-check/links";
import { buttonVariants } from "@/components/ui/button";
import { stepCounts } from "@/lib/api/public-check";
import { GALLERY } from "@/lib/public-check-gallery";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("publicCheck");
  return checkPageMetadata({
    title: t("galleryMetaTitle"),
    description: t("galleryLead", { count: GALLERY.length }),
    path: "/gallery",
    index: true,
  });
}

/** The gallery of analysed processes (HRP-930). */
export default async function PublicCheckGalleryPage() {
  const t = await getTranslations("publicCheck");
  const links = await checkLinks();
  const items = GALLERY.map((p) => ({
    slug: p.slug,
    title: p.title,
    domain: p.domain,
    ...stepCounts(p.result),
  }));
  return (
    <div className="space-y-8" data-testid="check-gallery">
      <header className="space-y-3">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{t("galleryTitle")}</h1>
        <p className="text-muted-foreground">{t("galleryLead", { count: GALLERY.length })}</p>
      </header>
      <GalleryList items={items} href={links.galleryHref} />
      <Link
        href={links.inputHref}
        className={buttonVariants({ size: "lg", className: "h-11 px-6 text-base" })}
        data-testid="check-gallery-cta"
      >
        {t("galleryCta")}
      </Link>
    </div>
  );
}
