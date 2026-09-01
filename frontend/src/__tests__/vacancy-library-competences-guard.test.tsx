// @vitest-environment jsdom
//
// HRP-687 review — PATCH …/competences is a replace-set built from the
// rows the section read on mount. When that GET failed the section used
// to fall back to an empty list, so opening the picker and pressing Save
// deleted every library competence on the vacancy and said "saved".
//
// Second finding: the picker button was live for every role on the page
// while the PATCH behind it is admin/recruiter only.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

let roles: string[] = ["recruiter"];
let competencesGetFails = false;

const apiGet = vi.fn((url: string) => {
  if (url.includes("/competences")) {
    return competencesGetFails
      ? Promise.reject(new Error("network"))
      : Promise.resolve([
          {
            id: "link-1",
            vacancy_id: "vac-1",
            competence_id: "comp-1",
            skill_level_ids: ["lvl-1"],
            source: "library",
          },
        ]);
  }
  // The generation-status banner polls for an active session.
  return Promise.resolve(null);
});
const apiPatch = vi.fn(() => Promise.resolve([]));

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    get: (url: string) => apiGet(url),
    patch: (...args: unknown[]) => apiPatch(...(args as [])),
    put: vi.fn(() => Promise.resolve({})),
    post: vi.fn(() => Promise.resolve({})),
    delete: vi.fn(() => Promise.resolve({})),
  },
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user: { roles } }),
}));

vi.mock("@/hooks/use-competence-tree", () => ({
  useCompetenceTree: () => ({ tree: [], loading: false, reload: vi.fn() }),
}));

const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: toastError, info: vi.fn() }),
}));

const { VacancyCompetencesSection } = await import(
  "@/app/(dashboard)/recruitment/requisitions/_components/VacancyCompetencesSection"
);

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  apiPatch.mockClear();
  apiGet.mockClear();
  toastError.mockClear();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render() {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <VacancyCompetencesSection
          // Only the fields this section reads.
          vacancy={{ id: "vac-1", status: "draft" } as never}
          profile={null}
          canEdit
          onProfileChange={() => {}}
        />
      </NextIntlClientProvider>,
    );
  });
  await act(async () => {
    await Promise.resolve();
  });
}

const pickerButton = () =>
  container.querySelector(
    '[data-testid="vacancy-competences-add-from-dict-btn"]',
  ) as HTMLButtonElement | null;

const dialog = () =>
  document.querySelector('[data-testid="vacancy-competences-library-dialog"]');

describe("Library competences — a failed read never becomes an empty save", () => {
  it("opens the picker when the read succeeded", async () => {
    roles = ["recruiter"];
    competencesGetFails = false;
    await render();
    await act(async () => {
      pickerButton()!.click();
    });
    expect(dialog()).not.toBeNull();
  });

  it("refuses to open the picker after a failed read, and sends no PATCH", async () => {
    roles = ["recruiter"];
    competencesGetFails = true;
    await render();
    await act(async () => {
      pickerButton()!.click();
    });
    // No dialog means no Save button means no replace-set PATCH built
    // from a baseline we never read.
    expect(dialog()).toBeNull();
    expect(apiPatch).not.toHaveBeenCalled();
    expect(toastError).toHaveBeenCalled();
    // The same click retried the read.
    expect(apiGet.mock.calls.filter(([u]) => u.includes("/competences")).length)
      .toBeGreaterThan(1);
  });

  it("disables the picker for a role that cannot PATCH", async () => {
    roles = ["hr"];
    competencesGetFails = false;
    await render();
    const btn = pickerButton();
    expect(btn).not.toBeNull();
    expect(btn!.disabled).toBe(true);
    expect(btn!.title).toContain("Only an admin or a recruiter");
  });
});
