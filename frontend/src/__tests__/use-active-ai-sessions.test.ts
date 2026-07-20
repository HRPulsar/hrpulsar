import { describe, expect, it } from "vitest";
import {
  activeAiSessionsKey,
  buildActiveSessionsMap,
  shouldPollActiveSessions,
  type ActiveAiSession,
} from "@/hooks/use-active-ai-sessions";

const ownIndicator: ActiveAiSession = {
  kind: "own",
  session_id: "own-1",
  scope: "competence_indicators",
  target_id: "comp-1",
  status: "running",
  position_id: null,
};

const otherIndicator: ActiveAiSession = {
  kind: "other",
  session_id: "other-1",
  user_full_name: "Vera",
  scope: "competence_indicators",
  target_id: "comp-1",
  status: "ready",
  position_id: null,
};

const otherGroup: ActiveAiSession = {
  kind: "other",
  session_id: "other-2",
  user_full_name: "Max",
  scope: "group",
  target_id: "group-9",
  status: "pending",
  position_id: null,
};

const otherWholeBase: ActiveAiSession = {
  kind: "other",
  session_id: "other-3",
  user_full_name: "Alex",
  scope: "whole_base",
  target_id: null,
  status: "running",
  position_id: null,
};

describe("activeAiSessionsKey", () => {
  it("namespaces by scope and target id", () => {
    expect(activeAiSessionsKey("group", "g1")).toBe("group:g1");
    expect(activeAiSessionsKey("competence_indicators", "c1")).toBe(
      "competence_indicators:c1",
    );
  });

  it("uses the literal `null` token for whole-base sessions", () => {
    expect(activeAiSessionsKey("whole_base", null)).toBe("whole_base:null");
  });
});

describe("buildActiveSessionsMap", () => {
  it("groups multiple sessions on the same competence together", () => {
    const map = buildActiveSessionsMap([ownIndicator, otherIndicator]);
    const bucket = map.get("competence_indicators:comp-1");
    expect(bucket).toHaveLength(2);
    expect(bucket?.map((s) => s.session_id).sort()).toEqual([
      "other-1",
      "own-1",
    ]);
  });

  it("keeps unrelated scopes / targets in their own buckets", () => {
    const map = buildActiveSessionsMap([
      ownIndicator,
      otherGroup,
      otherWholeBase,
    ]);
    expect([...map.keys()].sort()).toEqual([
      "competence_indicators:comp-1",
      "group:group-9",
      "whole_base:null",
    ]);
    expect(map.get("group:group-9")?.[0].session_id).toBe("other-2");
    expect(map.get("whole_base:null")?.[0].session_id).toBe("other-3");
  });

  it("returns an empty map for an empty input list", () => {
    expect(buildActiveSessionsMap([]).size).toBe(0);
  });
});

describe("shouldPollActiveSessions (HRP-232)", () => {
  it("polls while at least one own session is tracked", () => {
    expect(shouldPollActiveSessions(true, 0)).toBe(true);
  });

  it("polls while at least one other-user session is tracked", () => {
    expect(shouldPollActiveSessions(false, 1)).toBe(true);
  });

  it("polls when both own and others are present", () => {
    expect(shouldPollActiveSessions(true, 3)).toBe(true);
  });

  it("stops polling when nothing is being tracked", () => {
    expect(shouldPollActiveSessions(false, 0)).toBe(false);
  });
});
