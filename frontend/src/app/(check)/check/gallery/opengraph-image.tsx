import { connection } from "next/server";

import {
  CARD_SIZE,
  requestCardLocale,
  serviceCard,
} from "@/components/public-check/share-card";
import { publicCheckHost } from "@/lib/public-check-host";

export const size = CARD_SIZE;
export const contentType = "image/png";

/** The gallery's link preview: the card of the service (HRP-930). */
export default async function Image() {
  await connection();
  if (!publicCheckHost()) return new Response(null, { status: 404 });
  return serviceCard(await requestCardLocale());
}
