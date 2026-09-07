// @vitest-environment jsdom
//
// Review follow-ups on HRP-386/387 and HRP-684. Every recruitment viewer
// role may open an interview (GET), but PUT /recruitment/interviews/{id}
// and the consent send/resend endpoints are admin/recruiter only. The
// pencils on the interview page and the consent buttons on the candidate
// page used to render for hr / hiring_manager / manager and land on a
// 403. Same rule as the Add button in internal-candidates-block: an
// action only two roles have anywhere in recruitment is not shown to the
// others at all — there is nothing to explain.

import { NextIntlClientProvider } from "next-intl";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { ConsentRequest, Interview } from "@/lib/types";

let roles: string[] = [];
let consent: ConsentRequest | null = null;
let putFails = false;

const INTERVIEW: Interview = {
  id: "iv-1",
  candidate_vacancy_id: "cv-1",
  status: "scheduled",
  transcription_status: "pending",
  analysis_status: "pending",
  interviewer_ids: [],
  segments: [],
  ai_assessments: [],
};

const PENDING_CONSENT: ConsentRequest = {
  id: "cr-1",
  candidate_id: "cand-1",
  template_id: "tpl-1",
  email: "ada@example.com",
  status: "pending",
  expires_at: "2030-01-01T00:00:00Z",
  signed_at: null,
  created_at: "2026-09-01T10:00:00Z",
  last_sent_at: "2026-09-01T10:00:00Z",
};

const apiPut = vi.fn(() =>
  putFails ? Promise.reject(new Error("boom")) : Promise.resolve(INTERVIEW),
);

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    get: vi.fn((url: string) => {
      if (url.startsWith("/recruitment/interviews/"))
        return Promise.resolve(INTERVIEW);
      if (url.includes("/consent/latest")) return Promise.resolve(consent);
      // One row in the candidate section, so its row menu can be asserted.
      if (url.includes("/interviews?")) return Promise.resolve([INTERVIEW]);
      if (
        url.includes("/assessment-rounds") ||
        url === "/recruitment/interviewers"
      )
        return Promise.resolve([]);
      return Promise.reject(new Error(`not mocked: ${url}`));
    }),
    put: () => apiPut(),
    post: vi.fn(),
  },
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user: { roles } }),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "iv-1" }),
}));

vi.mock("@/hooks/use-cost-confirmation", () => ({
  useCreditGate: () => ({
    isSaas: false,
    cost: null,
    insufficient: false,
    refresh: vi.fn(),
  }),
}));

// The page pulls the player, upload zone and analysis panel through the
// barrel — none of them matter here and some want media elements jsdom
// does not have. The upload zone and the transcript viewer leave a marker
// so their gating can be asserted.
vi.mock("@/components/recruitment", () => ({
  AnalysisProgress: () => null,
  InterviewAnalysisPanel: () => null,
  InterviewPlayer: () => null,
  InterviewTextTranscriptDialog: () => null,
  InterviewUploadZone: () => <div data-testid="upload-zone-stub" />,
  RecruitmentBreadcrumbs: () => null,
  TranscriptEditDialog: () => null,
  TranscriptViewer: ({ onSegmentChange }: { onSegmentChange?: unknown }) => (
    <div
      data-testid="transcript-viewer-stub"
      data-editable={onSegmentChange ? "1" : "0"}
    />
  ),
}));

// A stand-in for the picker modal: while open it is a marker plus a Save
// that hands back one id, so the page's own close-on-success rule is
// driven without a base-ui dialog in the way.
vi.mock("@/components/recruitment/interviewer-picker", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/components/recruitment/interviewer-picker")
  >()),
  InterviewerPickerDialog: ({
    open,
    onSave,
  }: {
    open: boolean;
    onSave: (ids: string[]) => void;
  }) =>
    open ? (
      <button
        type="button"
        data-testid="picker-stub-save"
        onClick={() => onSave(["emp-1"])}
      />
    ) : null,
}));

const { default: InterviewDetailPage } = await import(
  "@/app/(dashboard)/recruitment/interviews/[id]/page"
);
const { CandidateInterviewsSection } = await import(
  "@/components/recruitment/candidate-interviews-section"
);
// Imported by file, not through the mocked barrel.
const { TranscriptViewer } = await import(
  "@/components/recruitment/transcript-viewer"
);

let container: HTMLDivElement;
let root: Root;

// jsdom has no layout: the viewer's sync-scroll effect calls this on the
// active segment.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => undefined;
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  putFails = false;
  apiPut.mockClear();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function render(withRoles: string[], node: ReactNode) {
  roles = withRoles;
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        {node}
      </NextIntlClientProvider>,
    );
  });
  await flush();
}

const byId = (id: string) =>
  container.querySelector(`[data-testid="${id}"]`) as HTMLElement | null;

const PENCILS = [
  "recruitment-interview-title-edit",
  "recruitment-interview-detail-type-edit",
  "recruitment-interview-detail-schedule-edit",
  "recruitment-interview-detail-duration-edit",
  "recruitment-interview-detail-interviewers-edit",
  "recruitment-interview-notes-edit",
  // PUT .../transcript — same gate.
  "recruitment-interview-btn-edit-transcript",
  // POST upload/*, transcript-text, transcribe, analyze — same gate.
  "upload-zone-stub",
  "recruitment-interview-btn-paste-text",
  "recruitment-interview-btn-transcribe",
  "recruitment-interview-btn-analyze",
];

describe("Interview page pencils — who may edit (HRP-386/387 follow-up)", () => {
  it("shows every pencil to a recruiter", async () => {
    await render(["recruiter"], <InterviewDetailPage />);
    expect(byId("recruitment-interview-details")).not.toBeNull();
    for (const id of PENCILS) expect(byId(id), id).not.toBeNull();
  });

  it("shows them to an admin", async () => {
    await render(["admin"], <InterviewDetailPage />);
    for (const id of PENCILS) expect(byId(id), id).not.toBeNull();
  });

  it("renders the page without any pencil for hr, a hiring manager and a manager", async () => {
    for (const role of ["hr", "hiring_manager", "manager"]) {
      await render([role], <InterviewDetailPage />);
      expect(byId("recruitment-interview-details"), role).not.toBeNull();
      for (const id of PENCILS) expect(byId(id), `${role}: ${id}`).toBeNull();
    }
  });
});

// PUT .../segments/{id} is admin/recruiter: the page hands the viewer a
// change callback only to an editor, and the viewer draws a per-segment
// pencil only when it has one.
describe("Inline segment edits — who may make them", () => {
  it("passes the viewer a change callback for a recruiter, none for hr", async () => {
    await render(["recruiter"], <InterviewDetailPage />);
    expect(byId("transcript-viewer-stub")!.dataset.editable).toBe("1");
    await render(["hr"], <InterviewDetailPage />);
    expect(byId("transcript-viewer-stub")!.dataset.editable).toBe("0");
  });

  it("draws the segment pencil only with a callback", async () => {
    const withSegment: Interview = {
      ...INTERVIEW,
      segments: [
        {
          id: "seg-1",
          interview_id: "iv-1",
          speaker: "A",
          start_sec: 0,
          end_sec: 4,
          text: "Hello",
        },
      ],
    };
    const pencil = () =>
      container.querySelector(
        `[data-testid="recruitment-segment-seg-1"] button[aria-label="${enMessages.recruitment.transcriptViewerEditSegment}"]`,
      );
    await render(
      ["recruiter"],
      <TranscriptViewer
        interview={withSegment}
        currentSec={0}
        onSeek={() => undefined}
        onSegmentChange={() => undefined}
      />,
    );
    expect(pencil()).not.toBeNull();
    await render(
      ["hr"],
      <TranscriptViewer
        interview={withSegment}
        currentSec={0}
        onSeek={() => undefined}
      />,
    );
    expect(pencil()).toBeNull();
  });
});

describe("Interviewer(s) picker stays open when the save fails", () => {
  it("closes on a successful PUT and keeps the selection on a failed one", async () => {
    await render(["recruiter"], <InterviewDetailPage />);
    act(() => byId("recruitment-interview-detail-interviewers-edit")!.click());
    expect(byId("picker-stub-save")).not.toBeNull();

    putFails = true;
    act(() => byId("picker-stub-save")!.click());
    await flush();
    expect(apiPut).toHaveBeenCalledTimes(1);
    // A failed PUT used to close the modal anyway, and the picked
    // interviewers went with it.
    expect(byId("picker-stub-save")).not.toBeNull();

    putFails = false;
    act(() => byId("picker-stub-save")!.click());
    await flush();
    expect(apiPut).toHaveBeenCalledTimes(2);
    expect(byId("picker-stub-save")).toBeNull();
  });
});

const section = (
  <CandidateInterviewsSection
    candidateId="cand-1"
    vacancyOptions={[
      { id: "vac-1", title: "Engineer", candidate_vacancy_id: "cv-1" },
    ]}
    candidateEmail="ada@example.com"
  />
);

// Schedule (POST .../interviews), the upload dropzone (POST .../upload/*)
// and the row menu (PUT interview, POST archive / restore) are all
// admin/recruiter on the backend.
const SECTION_ACTIONS = [
  "recruitment-candidate-interviews-schedule-btn",
  "recruitment-candidate-interviews-dropzone",
  "recruitment-candidate-interview-menu-iv-1",
];

describe("Candidate interviews section actions — who may act", () => {
  it("shows Schedule, the dropzone and the row menu to a recruiter", async () => {
    consent = null;
    await render(["recruiter"], section);
    for (const id of SECTION_ACTIONS) expect(byId(id), id).not.toBeNull();
  });

  it("keeps the list but none of them for hr", async () => {
    consent = null;
    await render(["hr"], section);
    expect(byId("recruitment-candidate-interview-status-iv-1")).not.toBeNull();
    for (const id of SECTION_ACTIONS) expect(byId(id), id).toBeNull();
  });
});

describe("Consent send / resend — who may do it (HRP-684 follow-up)", () => {
  it("offers Send consent to a recruiter when no request exists", async () => {
    consent = null;
    await render(["recruiter"], section);
    expect(byId("recruitment-candidate-interviews-consent-banner")).not.toBeNull();
    expect(byId("recruitment-candidate-interviews-consent-send-btn")).not.toBeNull();
  });

  it("offers Resend to an admin while the link is pending", async () => {
    consent = PENDING_CONSENT;
    await render(["admin"], section);
    expect(byId("recruitment-candidate-interviews-consent-resend-btn")).not.toBeNull();
  });

  it("keeps the banner but no button for hr and a hiring manager", async () => {
    for (const role of ["hr", "hiring_manager"]) {
      consent = null;
      await render([role], section);
      expect(byId("recruitment-candidate-interviews-consent-banner"), role).not.toBeNull();
      expect(byId("recruitment-candidate-interviews-consent-send-btn"), role).toBeNull();

      consent = PENDING_CONSENT;
      await render([role], section);
      expect(byId("recruitment-candidate-interviews-consent-banner"), role).not.toBeNull();
      expect(byId("recruitment-candidate-interviews-consent-resend-btn"), role).toBeNull();
    }
  });
});
