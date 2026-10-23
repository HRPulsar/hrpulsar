// @vitest-environment jsdom
//
// HRP-980 (QA 21.10): the interview recording could not be saved - the
// browser's own Save reused the 5-minute playback link and got S3's XML
// error. Whoever runs hiring (`manage`: admin, HR, recruiter by default)
// gets a Download button that signs a fresh link on every click; nobody
// gets the browser's Save.
// Playback rides the same 5-minute link: a seek after it expired (a
// citation clicked later) gets a fresh one instead of a dead player.

import { NextIntlClientProvider } from "next-intl";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import { api } from "@/lib/api";
import type { Interview } from "@/lib/types";

let roles: string[] = [];
let signed = 0;
let played = 0;

const INTERVIEW: Interview = {
  id: "iv-1",
  candidate_vacancy_id: "cv-1",
  status: "completed",
  type: "audio",
  audio_file_id: "f-1",
  transcription_status: "completed",
  analysis_status: "completed",
  interviewer_ids: [],
  interviewers: [],
  segments: [],
  ai_assessments: [],
};

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    get: vi.fn((url: string) => {
      if (url.endsWith("/media-url"))
        return Promise.resolve({ url: `https://s3/play-${++played}`, kind: "audio" });
      if (url.endsWith("/media-download-url"))
        return Promise.resolve({ url: `https://s3/save-${++signed}`, kind: "audio" });
      if (url.startsWith("/recruitment/interviews/"))
        return Promise.resolve(INTERVIEW);
      return Promise.resolve([]);
    }),
    put: vi.fn(),
    post: vi.fn(),
  },
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    user: {
      roles,
      sections: {
        recruitment: roles.some((r) => ["admin", "hr", "recruiter"].includes(r))
          ? "manage"
          : "view",
      },
    },
  }),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "iv-1" }) }));

vi.mock("@/hooks/use-cost-confirmation", () => ({
  useCreditGate: () => ({
    isSaas: false,
    cost: null,
    insufficient: false,
    refresh: vi.fn(),
  }),
}));

// The real player, everything else on the page stubbed out.
vi.mock("@/components/recruitment", async () => ({
  AnalysisProgress: () => null,
  InterviewAnalysisPanel: () => null,
  InterviewPlayer: (
    await import("@/components/recruitment/interview-player")
  ).InterviewPlayer,
  InterviewTextTranscriptDialog: () => null,
  InterviewUploadZone: () => null,
  RecruitmentBreadcrumbs: () => null,
  TranscriptEditDialog: () => null,
  TranscriptViewer: () => null,
}));

const { default: InterviewDetailPage } = await import(
  "@/app/(dashboard)/recruitment/interviews/[id]/page"
);

let container: HTMLDivElement;
let root: Root;
const clicked: string[] = [];

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  clicked.length = 0;
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
    function (this: HTMLAnchorElement) {
      clicked.push(this.href);
    },
  );
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

async function render(withRoles: string[], node: ReactNode) {
  roles = withRoles;
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        {node}
      </NextIntlClientProvider>,
    );
  });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

const byId = (id: string) =>
  container.querySelector(`[data-testid="${id}"]`) as HTMLElement | null;

describe("Interview recording Download (HRP-980)", () => {
  it("is there for admin, HR and recruiter, with a fresh link each click", async () => {
    for (const role of ["admin", "hr", "recruiter"]) {
      await render([role], <InterviewDetailPage />);
      const button = byId("recruitment-interview-player-download");
      expect(button, role).not.toBeNull();
      expect(button!.textContent).toContain(enMessages.recruitment.playerDownload);
      const before = signed;
      await act(async () => button!.click());
      await act(async () => button!.click());
      expect(signed - before, role).toBe(2);
      expect(clicked.slice(-2)).toEqual([
        `https://s3/save-${before + 1}`,
        `https://s3/save-${before + 2}`,
      ]);
    }
    expect(api.get).toHaveBeenCalledWith(
      "/recruitment/interviews/iv-1/media-download-url",
    );
  });

  it("is not there for a hiring manager or a manager, who still play it", async () => {
    for (const role of ["hiring_manager", "manager"]) {
      await render([role], <InterviewDetailPage />);
      expect(byId("recruitment-interview-player"), role).not.toBeNull();
      expect(byId("recruitment-interview-player-download"), role).toBeNull();
    }
  });

  it("keeps the browser's own Save off the player for everyone", async () => {
    for (const role of ["admin", "hiring_manager"]) {
      await render([role], <InterviewDetailPage />);
      expect(
        byId("recruitment-interview-player")!.getAttribute("controlslist"),
        role,
      ).toBe("nodownload");
    }
  });

  it("renews an expired playback link once and keeps the place", async () => {
    await render(["hiring_manager"], <InterviewDetailPage />);
    const player = () =>
      byId("recruitment-interview-player") as HTMLAudioElement;
    const first = player().getAttribute("src");
    // What S3 does to a seek once X-Amz-Expires has passed.
    await act(async () => {
      player().dispatchEvent(new Event("error"));
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    const renewed = player().getAttribute("src");
    expect(renewed).not.toBe(first);
    // A link that fails again right away is not renewed in a loop.
    await act(async () => {
      player().dispatchEvent(new Event("error"));
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(player().getAttribute("src")).toBe(renewed);
  });
});
