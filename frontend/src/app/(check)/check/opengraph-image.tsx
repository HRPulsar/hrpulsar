import { connection } from "next/server";

import {
  CARD_SIZE,
  requestCardLocale,
  serviceCard,
} from "@/components/public-check/share-card";
import { publicCheckHost } from "@/lib/public-check-host";

export const size = CARD_SIZE;
export const contentType = "image/png";

/** The link-preview card of the check pages that have none of their own -
 * the input page and the gallery (HRP-928). */
export default async function Image() {
  await connection();
  if (!publicCheckHost()) return new Response(null, { status: 404 });
  return serviceCard(await requestCardLocale());
}
