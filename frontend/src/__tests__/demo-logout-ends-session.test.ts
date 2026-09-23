// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  api: { post: vi.fn(() => Promise.resolve()) },
}));

import { api } from "@/lib/api";
import { logout } from "@/lib/auth";

const store = new Map<string, string>();
vi.stubGlobal("localStorage", {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, v),
  removeItem: (k: string) => void store.delete(k),
});

// HRP-897: signing out of a demo sandbox tells the backend to end it;
// a regular account's logout stays purely local.
describe("logout", () => {
  beforeEach(() => {
    vi.mocked(api.post).mockClear();
    // jsdom cannot navigate — swap location for a plain object.
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { href: "" },
    });
  });

  afterEach(() => {
    document.cookie = "demo_session=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("ends the sandbox when the session is a demo one", () => {
    document.cookie = "demo_session=1; path=/";
    localStorage.setItem("access_token", "demo-jwt");

    logout();

    expect(api.post).toHaveBeenCalledWith("/demo/end", undefined, {
      keepalive: true,
    });
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(window.location.href).toBe("/login");
  });

  it("does not call the demo endpoint for a regular account", () => {
    localStorage.setItem("access_token", "real-jwt");

    logout();

    expect(api.post).not.toHaveBeenCalled();
    expect(window.location.href).toBe("/login");
  });
});
