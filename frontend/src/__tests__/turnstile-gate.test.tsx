// @vitest-environment jsdom
import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useTurnstileGate, type TurnstileGate } from "@/lib/turnstile";

type WidgetProps = Record<string, (value?: string) => void>;

const mocks = vi.hoisted(() => ({
  lastProps: { current: null as Record<string, (value?: string) => void> | null },
  resetSpy: vi.fn(),
}));

vi.mock("@marsidev/react-turnstile", async () => {
  const { forwardRef, useEffect, useImperativeHandle } = await import("react");
  return {
    Turnstile: forwardRef(function MockTurnstile(
      props: WidgetProps,
      ref: React.Ref<{ reset: () => void }>,
    ) {
      useImperativeHandle(ref, () => ({ reset: mocks.resetSpy }));
      useEffect(() => {
        mocks.lastProps.current = props;
      });
      return null;
    }),
  };
});

const gateRef: { current: TurnstileGate | null } = { current: null };
const gate = () => gateRef.current!;
const widgetProps = () => mocks.lastProps.current!;

function Probe() {
  const g = useTurnstileGate();
  useEffect(() => {
    gateRef.current = g;
  });
  return <>{g.widget}</>;
}

let root: Root | null = null;

function render() {
  root = createRoot(document.createElement("div"));
  act(() => root!.render(<Probe />));
}

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT =
    true;
  vi.useFakeTimers();
  gateRef.current = null;
  mocks.lastProps.current = null;
  mocks.resetSpy.mockClear();
  window.__ENV__ = { NEXT_PUBLIC_TURNSTILE_SITE_KEY: "test-site-key" };
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  vi.useRealTimers();
  delete window.__ENV__;
});

describe("useTurnstileGate", () => {
  it("bypasses the gate when no site key is configured", () => {
    delete window.__ENV__;
    render();
    expect(gate().isReady).toBe(true);
    expect(gate().failed).toBe(false);
    expect(gate().widget).toBeNull();
  });

  it("starts unresolved, then becomes ready on widget success", () => {
    render();
    expect(gate().isReady).toBe(false);
    expect(gate().failed).toBe(false);

    act(() => widgetProps().onSuccess("tok-1"));
    expect(gate().isReady).toBe(true);
    expect(gate().token).toBe("tok-1");
  });

  it("flips to failed when the widget reports an error", () => {
    render();
    act(() => widgetProps().onError());
    expect(gate().failed).toBe(true);
    expect(gate().isReady).toBe(false);
  });

  it("flips to failed when the widget never resolves within the timeout", () => {
    render();
    act(() => void vi.advanceTimersByTime(15_000));
    expect(gate().failed).toBe(true);
  });

  it("renders escalated challenges instead of hiding them (interaction-only)", () => {
    render();
    const options = (widgetProps() as unknown as { options: { appearance?: string; size?: string } })
      .options;
    expect(options.appearance).toBe("interaction-only");
    expect(options.size).toBeUndefined();
  });

  it("pauses the watchdog while an interactive challenge is on screen", () => {
    render();
    act(() => widgetProps().onBeforeInteractive());
    act(() => void vi.advanceTimersByTime(60_000));
    expect(gate().failed).toBe(false);

    act(() => widgetProps().onSuccess("tok-3"));
    expect(gate().isReady).toBe(true);
  });

  it("does not fail after the timeout once a token was issued", () => {
    render();
    act(() => widgetProps().onSuccess("tok-1"));
    act(() => void vi.advanceTimersByTime(60_000));
    expect(gate().failed).toBe(false);
    expect(gate().isReady).toBe(true);
  });

  it("clears the failure if a token eventually arrives", () => {
    render();
    act(() => widgetProps().onError());
    expect(gate().failed).toBe(true);

    act(() => widgetProps().onSuccess("tok-2"));
    expect(gate().failed).toBe(false);
    expect(gate().isReady).toBe(true);
  });

  it("reset clears failure and token and restarts the widget", () => {
    render();
    act(() => widgetProps().onSuccess("tok-1"));
    act(() => widgetProps().onError());
    expect(gate().failed).toBe(true);

    act(() => gate().reset());
    expect(gate().failed).toBe(false);
    expect(gate().token).toBeNull();
    expect(gate().isReady).toBe(false);
    expect(mocks.resetSpy).toHaveBeenCalledTimes(1);

    // Watchdog re-arms after reset.
    act(() => void vi.advanceTimersByTime(15_000));
    expect(gate().failed).toBe(true);
  });
});
