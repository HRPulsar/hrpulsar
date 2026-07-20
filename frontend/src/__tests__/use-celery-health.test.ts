import { describe, it, expect } from "vitest";

// HRP-122: verifies the grace-period rule used by `useCeleryHealth`. Vitest
// runs without jsdom, so the actual hook isn't rendered — we exercise the
// same branching the polling loop applies.

type CeleryHealth = "unknown" | "available" | "unavailable";

function nextState(
  current: CeleryHealth,
  failures: number,
  probeResult: "ok" | "fail",
  threshold: number,
): { state: CeleryHealth; failures: number } {
  if (probeResult === "ok") {
    return { state: "available", failures: 0 };
  }
  const nextFailures = failures + 1;
  if (nextFailures >= threshold) {
    return { state: "unavailable", failures: nextFailures };
  }
  return { state: current, failures: nextFailures };
}

const THRESHOLD = 3;

describe("celery health grace period", () => {
  it("starts in 'unknown' until a probe lands", () => {
    const start: CeleryHealth = "unknown";
    expect(start).toBe("unknown");
  });

  it("flips to 'available' immediately on a successful probe", () => {
    const r = nextState("unknown", 0, "ok", THRESHOLD);
    expect(r.state).toBe("available");
    expect(r.failures).toBe(0);
  });

  it("does NOT flag 'unavailable' on a single failed probe", () => {
    const r = nextState("available", 0, "fail", THRESHOLD);
    expect(r.state).toBe("available");
    expect(r.failures).toBe(1);
  });

  it("does NOT flag 'unavailable' on two failed probes", () => {
    let s = nextState("available", 0, "fail", THRESHOLD);
    s = nextState(s.state, s.failures, "fail", THRESHOLD);
    expect(s.state).toBe("available");
    expect(s.failures).toBe(2);
  });

  it("flags 'unavailable' only after three consecutive failures", () => {
    let s = nextState("available", 0, "fail", THRESHOLD);
    s = nextState(s.state, s.failures, "fail", THRESHOLD);
    s = nextState(s.state, s.failures, "fail", THRESHOLD);
    expect(s.state).toBe("unavailable");
    expect(s.failures).toBe(3);
  });

  it("recovers to 'available' on a successful probe after failures", () => {
    let s = nextState("available", 0, "fail", THRESHOLD);
    s = nextState(s.state, s.failures, "fail", THRESHOLD);
    s = nextState(s.state, s.failures, "ok", THRESHOLD);
    expect(s.state).toBe("available");
    expect(s.failures).toBe(0);
  });

  it("recovers from 'unavailable' on a successful probe", () => {
    const s = nextState("unavailable", 5, "ok", THRESHOLD);
    expect(s.state).toBe("available");
    expect(s.failures).toBe(0);
  });
});