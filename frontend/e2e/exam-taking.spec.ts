import { test, expect } from "@playwright/test";
import {
  registerUser,
  setAuthTokens,
  createDivision,
  provisionTenantMember,
} from "./helpers";

const API_BASE = "http://localhost:8100/api";

// HRP-328: end-to-end employee exam taking — the take sheet with autosave,
// resume after close, gated submit, score display and the results review
// sheet with the answer key highlighted.
test.describe("Exam taking (HRP-328)", () => {
  test("employee takes an exam and reviews submitted results", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const division = await createDivision(
      { page, accessToken: admin.accessToken },
      `Exam div ${Date.now()}`,
    );
    const member = await provisionTenantMember(
      { page, accessToken: admin.accessToken },
      { roleCode: "employee", divisionId: division.id },
    );
    expect(member.employeeId).toBeTruthy();

    const authed = { Authorization: `Bearer ${admin.accessToken}` };

    // Admin: mass exam with a single-choice question and an essay.
    const meResp = await page.request.post(`${API_BASE}/mass-exams`, {
      headers: authed,
      data: { title: "HRP-328 e2e exam" },
    });
    expect(meResp.ok()).toBeTruthy();
    const massExam = await meResp.json();

    const qResp = await page.request.post(
      `${API_BASE}/mass-exams/${massExam.id}/questions`,
      {
        headers: authed,
        data: {
          title: "What is 2 + 2?",
          question_type: "single_choice",
          weight: 10,
          options: [
            { title: "4", sort_index: 0, is_correct: true },
            { title: "5", sort_index: 1, is_correct: false },
          ],
        },
      },
    );
    expect(qResp.ok()).toBeTruthy();
    const question = await qResp.json();
    const correctOption = question.options.find(
      (o: { is_correct: boolean }) => o.is_correct,
    );

    const essayResp = await page.request.post(
      `${API_BASE}/mass-exams/${massExam.id}/questions`,
      {
        headers: authed,
        data: {
          title: "Describe your approach",
          question_type: "essay",
          weight: 5,
          options: [],
        },
      },
    );
    expect(essayResp.ok()).toBeTruthy();
    const essay = await essayResp.json();

    const assignResp = await page.request.post(
      `${API_BASE}/mass-exams/${massExam.id}/employees`,
      { headers: authed, data: [member.employeeId] },
    );
    expect(assignResp.ok()).toBeTruthy();
    const [exam] = await assignResp.json();

    const sendResp = await page.request.post(
      `${API_BASE}/mass-exams/${massExam.id}/status`,
      { headers: authed, data: { status_code: "sent" } },
    );
    expect(sendResp.ok()).toBeTruthy();

    // Employee: the exam is listed with a take affordance.
    await setAuthTokens(page, member.accessToken, member.refreshToken);
    await page.goto("/exams");
    const row = page.getByTestId(`exams-row-${exam.id}`);
    await expect(row).toBeVisible({ timeout: 10000 });

    await page.getByTestId(`exams-row-${exam.id}-take`).click();
    const sheet = page.getByTestId("exam-take-sheet");
    await expect(sheet).toBeVisible();
    await expect(sheet).toContainText("0 / 2 questions answered");

    // Answering while the answer key stays hidden.
    const submitBtn = page.getByTestId("exam-take-submit");
    await expect(submitBtn).toBeDisabled();
    await page
      .locator(
        `label:has([data-testid="exam-take-option-${question.id}-${correctOption.id}"])`,
      )
      .click();
    await expect(sheet).toContainText("1 / 2 questions answered");
    await expect(submitBtn).toBeDisabled();

    // Close mid-way — answers persist, status flips to In progress.
    await page.keyboard.press("Escape");
    await expect(sheet).not.toBeVisible();
    await expect(row).toContainText("In progress", { timeout: 10000 });

    // Reopen — the saved answer is rehydrated.
    await page.getByTestId(`exams-row-${exam.id}-take`).click();
    await expect(sheet).toBeVisible();
    await expect(sheet).toContainText("1 / 2 questions answered");

    // Finish the essay and submit.
    await page
      .getByTestId(`exam-take-essay-${essay.id}`)
      .fill("Detailed essay answer");
    await expect(sheet).toContainText("2 / 2 questions answered");
    await expect(submitBtn).toBeEnabled();
    await submitBtn.click();
    await expect(sheet).not.toBeVisible({ timeout: 10000 });

    // The list shows the score and Completed status.
    await expect(row).toContainText("Completed", { timeout: 10000 });
    await expect(page.getByTestId(`exams-row-${exam.id}-score`)).toContainText(
      "10 / 15",
    );

    // Review sheet reveals the answer key.
    await page.getByTestId(`exams-row-${exam.id}-review`).click();
    const review = page.getByTestId("exam-review-sheet");
    await expect(review).toBeVisible();
    await expect(page.getByTestId("exam-review-score")).toContainText(
      "10 / 15",
    );
    await expect(
      page.getByTestId(`exam-review-verdict-${question.id}`),
    ).toContainText("Correct");
    await expect(
      page.getByTestId(
        `exam-review-option-${question.id}-${correctOption.id}`,
      ),
    ).toContainText("your answer");
  });
});
