"use client";

import { useEffect, useRef } from "react";

import { trackEvent, type CheckUtm, type FunnelEvent } from "@/lib/api/public-check";

/** Send `event` once per page, the first time `when` holds (HRP-931). The
 * ref survives re-renders and StrictMode's second effect run alike; a new
 * visit of the page is a new mount and counts again. */
export function useTrackOnce(event: FunnelEvent, utm: CheckUtm | null | undefined, when = true) {
  const sent = useRef(false);
  useEffect(() => {
    if (!when || sent.current) return;
    sent.current = true;
    trackEvent(event, utm);
  }, [event, utm, when]);
}
