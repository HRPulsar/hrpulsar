import type { MetadataRoute } from "next";

import { onCheckHost } from "@/components/public-check/links";
import { publicCheckOrigin } from "@/lib/public-check-host";

// The product frontend is never indexable — the public marketing site lives
// in the standalone marketing/ app (HRP-389). The one exception is the host
// of the public check (HRP-930): its input page and gallery are meant to be
// found. A result is somebody's own check and says noindex itself; it is not
// disallowed here, or the link-preview crawlers, which honour robots.txt,
// would never read its card (HRP-928).
export default async function robots(): Promise<MetadataRoute.Robots> {
  if (await onCheckHost()) {
    return {
      rules: { userAgent: "*", allow: "/" },
      sitemap: `${publicCheckOrigin()}/sitemap.xml`,
    };
  }
  return {
    rules: { userAgent: "*", disallow: "/" },
  };
}
