// @vitest-environment jsdom
//
// HRP-1015 REDO: an interviewer who later became a candidate of the vacancy
// (HRP-971 fences them off it) stays listed and ticked when the interview
// is edited. The dialog asks the list for this interview, and the backend
// keeps its interviewers in it; a new interview asks without one.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { Interview } from "@/lib/types";

const get = vi.fn((url: string) => {
  if (url.startsWith("/recruitment/interviewers"))
    // What the backend answers for this interview: Olga applied to the
    // vacancy after she was put on it, and is kept as its interviewer.
    return Promise.resolve([
      { id: "u-olga", full_name: "Olga Petrova", email: "o@x.io" },
    ]);
  return Promise.resolve([]);
});

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: { get: (url: string) => get(url), put: vi.fn(), post: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const { ScheduleInterviewDialog } = await import(
  "@/components/recruitment/schedule-interview-dialog"
);

const INTERVIEW = {
  id: "iv-1",
  candidate_vacancy_id: "cv-1",
  status: "scheduled",
  title: "Tech screen",
  interview_date: null,
  duration_minutes: 60,
  interviewer_ids: ["u-olga"],
  type: "audio",
  notes: null,
  round_id: null,
} as unknown as Interview;

const VACANCIES = [{ id: "v-1", title: "Backend", candidate_vacancy_id: "cv-1" }];
const PICKER = "recruitment-candidate-interviews-schedule-interviewers";

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  get.mockClear();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render(interview: Interview | null) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <ScheduleInterviewDialog
          open
          onOpenChange={() => {}}
          vacancyOptions={VACANCIES}
          vacancyId="v-1"
          interview={interview}
          onSaved={() => {}}
        />
      </NextIntlClientProvider>,
    );
  });
}

it("lists the interview's own interviewer, ticked, when editing", async () => {
  await render(INTERVIEW);

  expect(get).toHaveBeenCalledWith(
    "/recruitment/interviewers?candidate_vacancy_id=cv-1&interview_id=iv-1",
  );
  const option = document.querySelector(
    `[data-testid="${PICKER}-option-u-olga"]`,
  );
  expect(option).not.toBeNull();
  expect(option!.getAttribute("aria-checked")).toBe("true");
  expect(document.body.textContent).toContain("Olga Petrova");
});

it("asks without an interview when scheduling a new one", async () => {
  await render(null);

  expect(get).toHaveBeenCalledWith(
    "/recruitment/interviewers?candidate_vacancy_id=cv-1",
  );
});
