// @vitest-environment jsdom
//
// HRP-1052: the Google Ads loader is a silent no-op unless the deployment
// sets a conversion target, and the conversion event carries exactly the
// configured send_to. Nothing marketing-related may load without the env.

import { afterEach, beforeEach, expect, it } from "vitest";

import { loadGoogleAds, trackDemoConversion } from "@/lib/google-ads";

const SEND_TO = "AW-123456/someLabel";

beforeEach(() => {
  window.__ENV__ = undefined;
  window.dataLayer = undefined;
  window.gtag = undefined;
});

afterEach(() => {
  document.head.querySelectorAll("script").forEach((s) => s.remove());
});

const scripts = () =>
  Array.from(document.head.querySelectorAll("script")).map((s) => s.src);

it("does nothing without a configured conversion target", () => {
  loadGoogleAds();
  trackDemoConversion();

  expect(scripts()).toEqual([]);
  expect(window.dataLayer).toBeUndefined();
  expect(window.gtag).toBeUndefined();
});

it("loads gtag.js once and reports the conversion to the configured target", () => {
  window.__ENV__ = { NEXT_PUBLIC_GOOGLE_ADS_DEMO_CONVERSION: SEND_TO };

  loadGoogleAds();
  loadGoogleAds(); // a re-render must not inject a second script

  expect(scripts()).toEqual([
    "https://www.googletagmanager.com/gtag/js?id=AW-123456",
  ]);
  // The official snippet's queue: "js" + "config" before any event.
  const commands = window.dataLayer!.map((entry) =>
    Array.from(entry as ArrayLike<unknown>),
  );
  expect(commands[0][0]).toBe("js");
  expect(commands[1]).toEqual(["config", "AW-123456"]);

  trackDemoConversion();

  const last = Array.from(window.dataLayer!.at(-1) as ArrayLike<unknown>);
  expect(last).toEqual(["event", "conversion", { send_to: SEND_TO }]);
});

it("survives a broken gtag", () => {
  window.__ENV__ = { NEXT_PUBLIC_GOOGLE_ADS_DEMO_CONVERSION: SEND_TO };
  window.gtag = () => {
    throw new Error("blocked");
  };

  expect(() => trackDemoConversion()).not.toThrow();
});
