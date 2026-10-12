// Google Ads conversion tracking for the demo sandbox (HRP-1052).
//
// The deployment opts in by setting NEXT_PUBLIC_GOOGLE_ADS_DEMO_CONVERSION
// to the gtag `send_to` value ("AW-XXXXXXXX/label"). Unset — community,
// on-prem, white-label — everything here is a silent no-op and no
// marketing script ever reaches the page: the same contract as the
// backend's Umami beacon (ee/analytics.py). The loader must only be
// called from demo-session surfaces (the demo banner), so the script
// stays off regular tenants even on SaaS.

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
  }
}

function conversionSendTo(): string {
  return (
    (typeof window !== "undefined" &&
      window.__ENV__?.NEXT_PUBLIC_GOOGLE_ADS_DEMO_CONVERSION) ||
    process.env.NEXT_PUBLIC_GOOGLE_ADS_DEMO_CONVERSION ||
    ""
  );
}

/** Inject gtag.js once, ahead of the conversion it will carry. */
export function loadGoogleAds(): void {
  const sendTo = conversionSendTo();
  if (!sendTo || typeof document === "undefined" || window.gtag) return;
  const id = sendTo.split("/")[0];
  window.dataLayer = window.dataLayer || [];
  window.gtag = function gtag() {
    // gtag.js consumes Arguments objects from the queue — an array is
    // silently ignored, hence the official snippet's shape.
    // eslint-disable-next-line prefer-rest-params
    window.dataLayer!.push(arguments);
  };
  window.gtag("js", new Date());
  window.gtag("config", id);
  const script = document.createElement("script");
  script.async = true;
  script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(id)}`;
  document.head.appendChild(script);
}

/** Report the demo conversion to Google Ads. Never throws: ad tracking
 * must not break the flow that hosts it (our own tracker — the signup
 * request the same submit creates — already ran). */
export function trackDemoConversion(): void {
  const sendTo = conversionSendTo();
  if (!sendTo) return;
  try {
    window.gtag?.("event", "conversion", { send_to: sendTo });
  } catch {
    // Blocked or broken gtag is the visitor's business, not ours.
  }
}
