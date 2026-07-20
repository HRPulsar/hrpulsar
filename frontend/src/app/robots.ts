import type { MetadataRoute } from "next";

// The product frontend is never indexable — the public marketing site lives
// in the standalone marketing/ app (HRP-389).
export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", disallow: "/" },
  };
}
