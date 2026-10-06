import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";
import { ArrowLeft } from "lucide-react";

import { checkLinks, checkPageMetadata } from "@/components/public-check/links";
import { ResultBody } from "@/components/public-check/result-view";
import { buttonVariants } from "@/components/ui/button";
import { stepCounts } from "@/lib/api/public-check";
import { galleryProcess, midSentence } from "@/lib/public-check-gallery";

interface Props {
  params: Promise<{ slug: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const process = galleryProcess((await params).slug);
  if (!process) return {};
  const t = await getTranslations("publicCheck");
  return checkPageMetadata({
    title: t("galleryProcessTitle", { process: midSentence(process.title) }),
    description: t("galleryProcessDescription", stepCounts(process.result)),
    path: `/gallery/${process.slug}`,
    index: true,
  });
}

/** One analysed process of the gallery (HRP-930), in the view of a check
 * result - what a visitor who typed these steps in would get. */
export default async function PublicCheckGalleryProcessPage({ params }: Props) {
  const process = galleryProcess((await params).slug);
  if (!process) notFound();
  const t = await getTranslations("publicCheck");
  const links = await checkLinks();
  return (
    <article className="space-y-8" data-testid="check-gallery-process">
      <Link
        href={links.galleryHref}
        className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline"
        data-testid="check-gallery-back"
      >
        <ArrowLeft className="size-4" aria-hidden="true" />
        {t("galleryBack")}
      </Link>
      <header className="space-y-3">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          {t("galleryProcessTitle", { process: midSentence(process.title) })}
        </h1>
        <p className="text-muted-foreground">{t("galleryProcessNote")}</p>
      </header>

      <ResultBody
        result={process.result}
        lead={
          <p className="text-xl font-semibold" data-testid="check-gallery-steps">
            {t("galleryStepsLine", stepCounts(process.result))}
          </p>
        }
      />

      {process.sources.length > 0 ? (
        <section className="space-y-2" data-testid="check-gallery-sources">
          <h2 className="text-lg font-semibold">{t("gallerySources")}</h2>
          <ul className="space-y-1 text-sm">
            {process.sources.map((source) => (
              <li key={source.url}>
                <a
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="break-all text-primary hover:underline"
                >
                  {new URL(source.url).hostname.replace(/^www\./, "")}
                </a>
                <span className="text-muted-foreground">
                  {" · "}
                  {t(`galleryKind_${source.kind}`)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="space-y-3 rounded-xl border bg-muted/40 p-5 sm:p-6">
        <h2 className="text-xl font-semibold tracking-tight">{t("galleryCtaTitle")}</h2>
        <p>{t("galleryCtaText")}</p>
        <Link
          href={links.inputHref}
          className={buttonVariants({ size: "lg", className: "h-11 px-6 text-base" })}
          data-testid="check-gallery-cta"
        >
          {t("galleryCta")}
        </Link>
      </section>
    </article>
  );
}
