import type { MetadataRoute } from "next";
import { notFound } from "next/navigation";

import { onCheckHost } from "@/components/public-check/links";
import { GALLERY } from "@/lib/public-check-gallery";
import { publicCheckOrigin } from "@/lib/public-check-host";

/** Only the host of the public check has a sitemap (HRP-930): its input
 * page and the gallery. Results are not listed - nobody's check is public
 * by default. Anywhere else - the app host, a site without the check - an
 * honest 404, as before. */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  if (!(await onCheckHost())) notFound();
  const origin = publicCheckOrigin();
  return [
    { url: `${origin}/` },
    { url: `${origin}/gallery` },
    ...GALLERY.map((p) => ({ url: `${origin}/gallery/${p.slug}` })),
  ];
}
