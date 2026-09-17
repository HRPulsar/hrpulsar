// Review §3: `has_token` / `demo_session` were written without `Secure`,
// so the proxy's auth markers travelled on plaintext requests. The flag
// has to stay conditional — dev on http://localhost and the CI e2e stack
// serve plain http, where a `Secure` cookie is dropped by the browser and
// every navigation bounces back to /login.
import { afterEach, describe, expect, it, vi } from "vitest";

import { setClientCookie } from "@/lib/cookies";

function captureCookie(protocol: string): string[] {
  const written: string[] = [];
  vi.stubGlobal("window", { location: { protocol } });
  vi.stubGlobal("document", {
    set cookie(value: string) {
      written.push(value);
    },
  });
  return written;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("setClientCookie", () => {
  it("marks the cookie Secure over https", () => {
    const written = captureCookie("https:");
    setClientCookie("has_token", "1");
    expect(written).toEqual(["has_token=1; path=/; SameSite=Lax; Secure"]);
  });

  it("omits Secure over http so dev and e2e keep their session", () => {
    const written = captureCookie("http:");
    setClientCookie("demo_session", "1");
    expect(written).toEqual(["demo_session=1; path=/; SameSite=Lax"]);
  });
});
