import { describe, expect, it } from "vitest";
import {
  buildManualPayload,
  buildStagesPayload,
  manualPayloadValidationError,
  stageFromDefault,
  stageFromServer,
  stagesValidationError,
  validateBulkUploadSelection,
  type StageDraftRow,
} from "@/lib/recruitment-helpers";
import {
  BULK_UPLOAD_MAX_FILE_BYTES,
  BULK_UPLOAD_MAX_FILES,
  BULK_UPLOAD_MAX_TOTAL_BYTES,
  type VacancyStage,
} from "@/lib/recruitment-types";

function file(name: string, size: number, type: string) {
  return { name, size, type };
}

// HRP-476: the validators return i18n keys now — the wording lives in
// messages/*.json. The stub echoes the key back and records the values so
// the tests pin the contract (key + placeholders), never the English copy.
let lastValues: Record<string, string | number> | undefined;
const t = (key: string, values?: Record<string, string | number>): string => {
  lastValues = values;
  return key;
};

describe("validateBulkUploadSelection", () => {
  it("rejects an empty selection", () => {
    expect(validateBulkUploadSelection(t, [])).toBe("bulkUploadPickFile");
  });

  it("accepts PDFs and DOCX under the byte cap", () => {
    expect(
      validateBulkUploadSelection(t, [
        file("cv.pdf", 1024, "application/pdf"),
        file(
          "cv.docx",
          1024,
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
      ]),
    ).toBeNull();
  });

  it("rejects unknown MIME types", () => {
    expect(
      validateBulkUploadSelection(t, [file("cv.jpg", 1024, "image/jpeg")]),
    ).toBe("bulkUploadUnsupportedType");
    expect(lastValues).toEqual({ name: "cv.jpg" });
  });

  it("falls back to extension when MIME is empty", () => {
    expect(
      validateBulkUploadSelection(t, [file("cv.pdf", 1024, "")]),
    ).toBeNull();
    expect(
      validateBulkUploadSelection(t, [file("cv.exe", 1024, "")]),
    ).toBe("bulkUploadUnsupportedType");
  });

  it("rejects oversized files with the correct cap", () => {
    expect(
      validateBulkUploadSelection(t, [
        file("big.pdf", BULK_UPLOAD_MAX_FILE_BYTES + 1, "application/pdf"),
      ]),
    ).toBe("bulkUploadFileTooLarge");
    expect(lastValues).toEqual({ name: "big.pdf", max: 10 });
  });

  it(`rejects more than ${BULK_UPLOAD_MAX_FILES} files`, () => {
    const tooMany = Array.from({ length: BULK_UPLOAD_MAX_FILES + 1 }, (_, i) =>
      file(`cv-${i}.pdf`, 1024, "application/pdf"),
    );
    expect(validateBulkUploadSelection(t, tooMany)).toBe(
      "bulkUploadTooManyFiles",
    );
    expect(lastValues).toEqual({ max: BULK_UPLOAD_MAX_FILES });
  });

  it("rejects when the aggregate batch size exceeds the total cap", () => {
    // 11 × 10 MB = 110 MB → above the 100 MB total cap.
    const overTotal = Array.from({ length: 11 }, (_, i) =>
      file(`cv-${i}.pdf`, BULK_UPLOAD_MAX_FILE_BYTES, "application/pdf"),
    );
    expect(validateBulkUploadSelection(t, overTotal)).toBe(
      "bulkUploadBatchTooLarge",
    );
    expect(BULK_UPLOAD_MAX_TOTAL_BYTES).toBeGreaterThan(
      BULK_UPLOAD_MAX_FILE_BYTES,
    );
  });
});

describe("manualPayloadValidationError", () => {
  const base = {
    full_name: "Anna Smirnova",
    email: "anna@example.com",
    phone: "",
    linkedin_url: "",
    location: "",
    current_position: "",
    years_of_experience: "",
    source: "",
    notes: "",
  };

  it("requires full name", () => {
    expect(
      manualPayloadValidationError(t, { ...base, full_name: "" }),
    ).toBe("candidateFullNameRequired");
  });

  it("requires at least email or phone", () => {
    expect(
      manualPayloadValidationError(t, { ...base, email: "", phone: "" }),
    ).toBe("candidateContactRequired");
  });

  it("passes when email-only or phone-only", () => {
    expect(manualPayloadValidationError(t, base)).toBeNull();
    expect(
      manualPayloadValidationError(t, { ...base, email: "", phone: "+1234" }),
    ).toBeNull();
  });
});

describe("buildManualPayload", () => {
  const form = {
    full_name: "  Anna ",
    email: " anna@example.com ",
    phone: "",
    linkedin_url: "",
    location: "",
    current_position: " Senior backend ",
    years_of_experience: "8",
    source: "",
    notes: "  Top of funnel  ",
  };

  it("trims and nulls out empty fields", () => {
    const payload = buildManualPayload(form);
    expect(payload.full_name).toBe("Anna");
    expect(payload.email).toBe("anna@example.com");
    expect(payload.phone).toBeNull();
    expect(payload.linkedin_url).toBeNull();
    expect(payload.current_position).toBe("Senior backend");
    expect(payload.years_of_experience).toBe(8);
    expect(payload.notes).toBe("Top of funnel");
    expect(payload.link_candidate_id).toBeNull();
  });

  it("forwards link_candidate_id when supplied", () => {
    const payload = buildManualPayload(form, "11111111-1111-1111-1111-111111111111");
    expect(payload.link_candidate_id).toBe(
      "11111111-1111-1111-1111-111111111111",
    );
  });

  it("returns null years for non-numeric input", () => {
    expect(
      buildManualPayload({ ...form, years_of_experience: "abc" })
        .years_of_experience,
    ).toBeNull();
  });
});

// --- stages --------------------------------------------------------------

function stage(overrides: Partial<VacancyStage>): VacancyStage {
  return {
    id: overrides.id ?? "00000000-0000-0000-0000-000000000001",
    tenant_id: null,
    vacancy_id: null,
    name: overrides.name ?? "New",
    code: overrides.code ?? "new",
    sort_order: overrides.sort_order ?? 0,
    is_terminal: overrides.is_terminal ?? false,
    stage_type: overrides.stage_type ?? "active",
    color: overrides.color ?? null,
  };
}

describe("stageFromServer / stageFromDefault", () => {
  it("preserves server id when materialising an existing override", () => {
    const row = stageFromServer(
      stage({ id: "11111111-1111-1111-1111-111111111111", name: "Screening" }),
    );
    expect(row.id).toBe("11111111-1111-1111-1111-111111111111");
    expect(row.key).toBe(row.id);
  });

  it("strips server id when seeding from tenant defaults", () => {
    let counter = 0;
    const row = stageFromDefault(stage({ name: "Hired" }), () =>
      `k${++counter}`,
    );
    expect(row.id).toBeNull();
    expect(row.key).toBe("k1");
  });
});

describe("buildStagesPayload", () => {
  const draft: StageDraftRow[] = [
    {
      key: "a",
      id: "id-a",
      name: " New ",
      code: " new ",
      color: " slate ",
      stage_type: "active",
    },
    {
      key: "b",
      id: null,
      name: "Hired",
      code: "hired",
      color: "",
      stage_type: "terminal_positive",
    },
  ];

  it("assigns sort_order by array index", () => {
    const out = buildStagesPayload(draft);
    expect(out[0].sort_order).toBe(0);
    expect(out[1].sort_order).toBe(1);
  });

  it("trims whitespace and nulls empty colors", () => {
    const out = buildStagesPayload(draft);
    expect(out[0].name).toBe("New");
    expect(out[0].code).toBe("new");
    expect(out[0].color).toBe("slate");
    expect(out[1].color).toBeNull();
  });

  it("forwards stage_type as-is", () => {
    const out = buildStagesPayload(draft);
    expect(out[1].stage_type).toBe("terminal_positive");
  });
});

describe("stagesValidationError", () => {
  it("requires at least one stage", () => {
    expect(stagesValidationError(t, [])).toBe("stagesAtLeastOne");
  });

  it("rejects empty name or code", () => {
    const base: StageDraftRow = {
      key: "k",
      id: null,
      name: "",
      code: "c",
      color: "",
      stage_type: "active",
    };
    expect(stagesValidationError(t, [base])).toBe("stageNameCodeRequired");
    expect(
      stagesValidationError(t, [{ ...base, name: "ok", code: "" }]),
    ).toBe("stageNameCodeRequired");
  });
});

describe("updateParsedResumeSection", () => {
  it("replaces summary and preserves other fields", async () => {
    const { updateParsedResumeSection } = await import(
      "@/lib/recruitment-helpers"
    );
    const out = updateParsedResumeSection(
      { skills: ["Python"], summary: "old" },
      "summary",
      "new value",
    );
    expect(out.summary).toBe("new value");
    expect(out.skills).toEqual(["Python"]);
  });

  it("normalises empty summary to null", async () => {
    const { updateParsedResumeSection } = await import(
      "@/lib/recruitment-helpers"
    );
    expect(
      updateParsedResumeSection({ summary: "x" }, "summary", "   ").summary,
    ).toBeNull();
  });

  it("dedupes and trims skills", async () => {
    const { updateParsedResumeSection } = await import(
      "@/lib/recruitment-helpers"
    );
    const out = updateParsedResumeSection({}, "skills", [
      " Python ",
      "Python",
      "",
      "FastAPI",
    ]);
    expect(out.skills).toEqual(["Python", "FastAPI"]);
  });

  it("prunes empty experience rows and normalises strings", async () => {
    const { updateParsedResumeSection } = await import(
      "@/lib/recruitment-helpers"
    );
    const out = updateParsedResumeSection({}, "experience", [
      { title: " Lead ", company: "Acme", description: "" },
      { title: "", company: "" },
      { title: null, company: null, description: "   " },
    ]);
    expect(out.experience).toEqual([
      {
        // helper mirrors the cleaned value to position (canonical) + role
        // (back-compat) + title (editor) — see pruneExperience.
        position: "Lead",
        role: "Lead",
        title: "Lead",
        company: "Acme",
        start_date: null,
        end_date: null,
        description: null,
      },
    ]);
  });

  it("prunes blank education and certificate rows", async () => {
    const { updateParsedResumeSection } = await import(
      "@/lib/recruitment-helpers"
    );
    expect(
      updateParsedResumeSection({}, "education", [
        { institution: "" },
        { institution: "MIT", degree: " BSc " },
      ]).education,
    ).toEqual([
      {
        institution: "MIT",
        degree: "BSc",
        field: null,
        start_date: null,
        end_date: null,
      },
    ]);
    expect(
      updateParsedResumeSection({}, "certificates", [
        { name: "", issuer: "", issued_at: "" },
        { name: "AWS SAA", issuer: "Amazon", issued_at: "2024-04" },
      ]).certificates,
    ).toEqual([
      { name: "AWS SAA", issuer: "Amazon", issued_at: "2024-04" },
    ]);
  });

  it("collapses blank language rows", async () => {
    const { updateParsedResumeSection } = await import(
      "@/lib/recruitment-helpers"
    );
    expect(
      updateParsedResumeSection({}, "languages", [
        { name: "", level: "" },
        { name: "English ", level: "C2" },
      ]).languages,
    ).toEqual([{ name: "English", level: "C2" }]);
  });
});
