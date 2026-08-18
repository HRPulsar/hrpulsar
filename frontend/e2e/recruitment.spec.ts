import { test, expect } from "./fixtures";
import { registerUser, loginViaUI, completeOnboarding } from "./helpers";

const API_BASE = "http://localhost:8100/api";

test.describe("Recruitment Module", () => {
  test.describe("Navigation", () => {
    test("sidebar shows Recruitment link", async ({ page }) => {
      const { email, password } = await registerUser(page);
      await loginViaUI(page, email, password);
      await expect(page).toHaveURL(/\/dashboard/, { timeout: 10000 });
      await expect(
        page.getByTestId("sidebar-link-recruitment"),
      ).toBeVisible();
    });

    test("clicking Recruitment navigates to vacancy list", async ({
      page,
    }) => {
      const { email, password, accessToken } = await registerUser(page);
      // Without completing onboarding, the dashboard's recruitment link
      // routes through the onboarding gate first.
      await completeOnboarding({ page, accessToken });
      await loginViaUI(page, email, password);
      await page.getByTestId("sidebar-link-recruitment").click();
      await expect(page).toHaveURL(/\/recruitment/, { timeout: 10000 });
    });

    // HRP-353: section tabs on the top-level recruitment pages.
    test("section tabs switch between recruitment modules", async ({
      page,
    }) => {
      const { email, password, accessToken } = await registerUser(page);
      await completeOnboarding({ page, accessToken });
      await loginViaUI(page, email, password);
      await page.goto("/recruitment/requisitions");
      await expect(page.getByTestId("recruitment-tab-vacancies")).toBeVisible({
        timeout: 10000,
      });
      // Admin sees the Settings tab.
      await expect(page.getByTestId("recruitment-tab-settings")).toBeVisible();

      await page.getByTestId("recruitment-tab-candidates").click();
      await expect(page).toHaveURL(/\/recruitment\/candidates/, {
        timeout: 10000,
      });
      await page.getByTestId("recruitment-tab-reports").click();
      await expect(page).toHaveURL(/\/recruitment\/reports/, {
        timeout: 10000,
      });
      await page.getByTestId("recruitment-tab-audit").click();
      await expect(page).toHaveURL(/\/recruitment\/audit-log/, {
        timeout: 10000,
      });
    });
  });

  test.describe("Vacancy CRUD", () => {
    test("vacancy list shows empty state initially", async ({ page }) => {
      const { email, password } = await registerUser(page);
      await loginViaUI(page, email, password);
      await page.goto("/recruitment/requisitions");
      await expect(
        page.getByTestId("recruitment-vacancy-list"),
      ).toBeVisible({ timeout: 10000 });
      await expect(
        page.getByTestId("recruitment-vacancy-empty"),
      ).toBeVisible();
    });

    test("create vacancy and verify in list", async ({ page }) => {
      const { email, password } = await registerUser(page);
      await loginViaUI(page, email, password);

      // Navigate to create form
      await page.goto("/recruitment/requisitions/new");
      await expect(
        page.getByTestId("recruitment-vacancy-create-form"),
      ).toBeVisible({ timeout: 10000 });

      // Fill form
      await page
        .getByTestId("recruitment-vacancy-input-title")
        .fill("QA Engineer");

      // Save draft
      await page.getByTestId("recruitment-vacancy-btn-save-draft").click();

      // Should redirect to detail
      await expect(page).toHaveURL(/\/recruitment\/requisitions\//, {
        timeout: 10000,
      });
      await expect(
        page.getByTestId("recruitment-vacancy-detail"),
      ).toBeVisible();
    });

    test("vacancy detail shows overview tab", async ({ page }) => {
      const { email, password, accessToken } = await registerUser(page);

      // Create vacancy via API
      const resp = await page.request.post(
        `${API_BASE}/recruitment/vacancies`,
        {
          headers: { Authorization: `Bearer ${accessToken}` },
          data: {
            title: "Backend Developer",
            description: "Build APIs",
          },
        },
      );
      expect(resp.ok()).toBeTruthy();
      const vacancy = await resp.json();

      await loginViaUI(page, email, password);
      await page.goto(`/recruitment/requisitions/${vacancy.id}`);
      await expect(
        page.getByTestId("recruitment-vacancy-detail"),
      ).toBeVisible({ timeout: 10000 });
      await expect(
        page.getByTestId("recruitment-vacancy-tab-overview"),
      ).toBeVisible();
    });
  });

  test.describe("Candidate CRUD", () => {
    test("candidate list shows empty state", async ({ page }) => {
      const { email, password } = await registerUser(page);
      await loginViaUI(page, email, password);
      await page.goto("/recruitment/candidates");
      await expect(
        page.getByTestId("recruitment-candidate-list"),
      ).toBeVisible({ timeout: 10000 });
      await expect(
        page.getByTestId("recruitment-candidate-empty"),
      ).toBeVisible();
    });

    test("create candidate via API and verify in list", async ({ page }) => {
      const { email, password, accessToken } = await registerUser(page);

      // Create candidate via API
      const resp = await page.request.post(
        `${API_BASE}/recruitment/candidates`,
        {
          headers: { Authorization: `Bearer ${accessToken}` },
          data: {
            first_name: "Ivan",
            last_name: "Petrov",
            email: "ivan.petrov@example.com",
            source: "linkedin",
          },
        },
      );
      expect(resp.ok()).toBeTruthy();

      await loginViaUI(page, email, password);
      await page.goto("/recruitment/candidates");
      await expect(
        page.getByTestId("recruitment-candidate-list"),
      ).toBeVisible({ timeout: 10000 });
      // Should see the candidate in the table
      await expect(page.getByText("Ivan Petrov")).toBeVisible({
        timeout: 5000,
      });
    });

    // HRP-181 REDO: the candidate detail page is a card layout now
    // (PersonalCard + FilesCard + VacancyApplicationsCard) — the old
    // tabbed structure is gone, so the test asserts the card sections.
    test("candidate detail shows card layout sections", async ({ page }) => {
      const { email, password, accessToken } = await registerUser(page);

      const resp = await page.request.post(
        `${API_BASE}/recruitment/candidates`,
        {
          headers: { Authorization: `Bearer ${accessToken}` },
          data: {
            first_name: "Maria",
            last_name: "Ivanova",
            email: "maria@example.com",
          },
        },
      );
      const candidate = await resp.json();

      await loginViaUI(page, email, password);
      await page.goto(`/recruitment/candidates/${candidate.id}`);
      await expect(
        page.getByTestId("recruitment-candidate-detail"),
      ).toBeVisible({ timeout: 10000 });
      await expect(page.getByTestId("candidate-card-full-name")).toHaveText(
        /Maria Ivanova/,
      );
      await expect(
        page.getByTestId("candidate-card-section-personal"),
      ).toBeVisible();
      await expect(
        page.getByTestId("candidate-card-section-files"),
      ).toBeVisible();
      await expect(
        page.getByTestId("candidate-card-section-applications"),
      ).toBeVisible();
    });
  });

  test.describe("Deduplication", () => {
    test("creating candidate with duplicate email returns 409", async ({
      page,
    }) => {
      const { accessToken } = await registerUser(page);
      const candidateEmail = `dedup-${Date.now()}@example.com`;

      // First candidate
      const resp1 = await page.request.post(
        `${API_BASE}/recruitment/candidates`,
        {
          headers: { Authorization: `Bearer ${accessToken}` },
          data: {
            first_name: "First",
            last_name: "Candidate",
            email: candidateEmail,
          },
        },
      );
      expect(resp1.ok()).toBeTruthy();

      // Duplicate
      const resp2 = await page.request.post(
        `${API_BASE}/recruitment/candidates`,
        {
          headers: { Authorization: `Bearer ${accessToken}` },
          data: {
            first_name: "Duplicate",
            last_name: "Candidate",
            email: candidateEmail,
          },
        },
      );
      expect(resp2.status()).toBe(409);
    });
  });

  test.describe("Candidate GDPR surface (R3b)", () => {
    // HRP-181 REDO: the candidate-page Interviews tab + ConsentBanner
    // were removed in the Stage 4/5 redesign — interviews live under
    // /recruitment/interviews (covered by interview-upload.spec.ts) and
    // the consent/GDPR surface is the per-candidate GDPR page.
    test("candidate GDPR page shows export and erase actions", async ({
      page,
    }) => {
      const { email, password, accessToken } = await registerUser(page);
      const candResp = await page.request.post(
        `${API_BASE}/recruitment/candidates`,
        {
          headers: { Authorization: `Bearer ${accessToken}` },
          data: {
            first_name: "Ivan",
            last_name: "Interview",
            email: `iv-${Date.now()}@example.com`,
          },
        },
      );
      const candidate = await candResp.json();

      await loginViaUI(page, email, password);
      await page.goto(`/recruitment/candidates/${candidate.id}/gdpr`);
      await expect(page.getByTestId("candidate-gdpr-page")).toBeVisible({
        timeout: 10000,
      });
      await expect(page.getByTestId("gdpr-btn-export")).toBeVisible();
      await expect(page.getByTestId("gdpr-btn-erase")).toBeVisible();
    });
  });

  test.describe("Public consent page (R3b)", () => {
    test("invalid token shows error state", async ({ page }) => {
      // Token routes are public (no auth header) so we just hit the page.
      await page.goto("/recruitment/consent/invalid-token-xxxxx");
      await expect(
        page.getByTestId("consent-page-error"),
      ).toBeVisible({ timeout: 10000 });
    });
  });

  test.describe("Cmd+K Search", () => {
    test("global search finds vacancies", async ({ page }) => {
      const { email, password, accessToken } = await registerUser(page);

      // Create vacancy via API
      await page.request.post(`${API_BASE}/recruitment/vacancies`, {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: { title: "Unique QA Position XYZ" },
      });

      await loginViaUI(page, email, password);
      await page.getByTestId("header-search").click();
      await page.getByTestId("header-search").fill("Unique QA");

      // Wait for search results
      await expect(page.getByText("Vacancy")).toBeVisible({ timeout: 5000 });
      await expect(page.getByText("Unique QA Position XYZ")).toBeVisible();
    });
  });
});
