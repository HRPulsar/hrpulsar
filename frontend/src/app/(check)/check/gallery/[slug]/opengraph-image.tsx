import { connection } from "next/server";

import {
  CARD_SIZE,
  galleryCard,
  requestCardLocale,
} from "@/components/public-check/share-card";
import { galleryProcess } from "@/lib/public-check-gallery";
import { publicCheckHost } from "@/lib/public-check-host";

export const size = CARD_SIZE;
export const contentType = "image/png";

/** A gallery process's link preview (HRP-930): "Can AI do <process>?"
 * and how many of its steps go to an agent. */
export default async function Image({ params }: { params: Promise<{ slug: string }> }) {
  await connection();
  const process = galleryProcess((await params).slug);
  if (!publicCheckHost() || !process) return new Response(null, { status: 404 });
  return galleryCard(process, await requestCardLocale());
}
