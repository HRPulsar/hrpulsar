import { connection } from "next/server";

import {
  CARD_SIZE,
  fetchCheck,
  requestCardLocale,
  resultCard,
  serviceCard,
} from "@/components/public-check/share-card";
import { publicCheckHost } from "@/lib/public-check-host";

export const size = CARD_SIZE;
export const contentType = "image/png";

/** The link-preview card of a result (HRP-928): "AI takes N of my M
 * steps" and the process. Read per request - a check still running, or
 * gone, gets the card of the service, never an error. */
export default async function Image({ params }: { params: Promise<{ token: string }> }) {
  await connection();
  if (!publicCheckHost()) return new Response(null, { status: 404 });
  const check = await fetchCheck((await params).token);
  return check ? resultCard(check) : serviceCard(await requestCardLocale());
}
