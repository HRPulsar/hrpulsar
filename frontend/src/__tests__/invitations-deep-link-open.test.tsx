// @vitest-environment jsdom
//
// HRP-174 REDO: arriving at /settings/invitations?open=invite auto-opens
// the Send invitation dialog. The first implementation re-fired its effect
// on every render — `onOpen` is a fresh closure each time and it sat in the
// dependency array — so closing the dialog immediately reopened it: Cancel,
// the X icon and the outside click all looked dead, and F5 did not help
// because `open=invite` stayed in the URL.
//
// This is a behavioural test on purpose. The regression is "the effect runs
// again on re-render", which no source-grep can see: the fix has to be
// pinned by actually re-rendering and counting the calls.

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
let currentParams = new URLSearchParams();
let currentPath = "/settings/invitations";

vi.mock("next/navigation", () => ({
  useSearchParams: () => currentParams,
  usePathname: () => currentPath,
  useRouter: () => ({ replace }),
}));

const { DeepLinkInviteOpener } = await import(
  "@/components/settings/deep-link-invite-opener"
);

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  replace.mockClear();
  currentParams = new URLSearchParams();
  currentPath = "/settings/invitations";
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

/** Render with a brand-new `onOpen` closure, exactly like the page does. */
function renderWith(onOpen: () => void) {
  act(() => {
    root.render(<DeepLinkInviteOpener onOpen={() => onOpen()} />);
  });
}

describe("DeepLinkInviteOpener (HRP-174)", () => {
  it("opens the dialog once for open=invite", () => {
    const onOpen = vi.fn();
    currentParams = new URLSearchParams("open=invite");
    renderWith(onOpen);
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("does not re-open on re-render — the close must stick", () => {
    const onOpen = vi.fn();
    currentParams = new URLSearchParams("open=invite");
    renderWith(onOpen);
    expect(onOpen).toHaveBeenCalledTimes(1);

    // The parent re-renders whenever any of its state changes — including
    // the setInviteOpen(false) that closes the dialog. Each re-render hands
    // down a fresh `onOpen` closure. The old code re-fired here.
    renderWith(onOpen);
    renderWith(onOpen);
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("strips open=invite from the URL so a reload does not reopen it", () => {
    currentParams = new URLSearchParams("open=invite");
    renderWith(vi.fn());
    expect(replace).toHaveBeenCalledTimes(1);
    expect(replace).toHaveBeenCalledWith("/settings/invitations", {
      scroll: false,
    });
  });

  it("keeps unrelated query parameters", () => {
    currentParams = new URLSearchParams("status=pending&open=invite");
    renderWith(vi.fn());
    expect(replace).toHaveBeenCalledWith(
      "/settings/invitations?status=pending",
      { scroll: false },
    );
  });

  it("does nothing without the parameter", () => {
    const onOpen = vi.fn();
    renderWith(onOpen);
    expect(onOpen).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
  });

  it("ignores an unrelated open value", () => {
    const onOpen = vi.fn();
    currentParams = new URLSearchParams("open=something-else");
    renderWith(onOpen);
    expect(onOpen).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
  });

  it("re-arms once the parameter is gone", () => {
    const onOpen = vi.fn();
    currentParams = new URLSearchParams("open=invite");
    renderWith(onOpen);
    expect(onOpen).toHaveBeenCalledTimes(1);

    // Our own router.replace lands: the parameter disappears.
    currentParams = new URLSearchParams();
    renderWith(onOpen);
    expect(onOpen).toHaveBeenCalledTimes(1);

    // A fresh deep link arrives while the page stayed mounted.
    currentParams = new URLSearchParams("open=invite");
    renderWith(onOpen);
    expect(onOpen).toHaveBeenCalledTimes(2);
  });
});
