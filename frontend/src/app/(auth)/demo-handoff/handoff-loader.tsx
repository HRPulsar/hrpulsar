"use client";

import dynamic from "next/dynamic";

// The handoff reads window.location.hash to lift a one-shot demo JWT
// off the URL fragment; SSR would render with no fragment and force a
// hydration mismatch. ssr:false is only allowed inside a Client
// Component, so this loader is the seam.
const DemoHandoffClient = dynamic(() => import("./handoff-client"), {
  ssr: false,
});

export default function DemoHandoffLoader() {
  return <DemoHandoffClient />;
}
