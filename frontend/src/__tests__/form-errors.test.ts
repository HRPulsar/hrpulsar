import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";
import { parseFormError } from "@/lib/form-errors";

describe("parseFormError (HRP-399)", () => {
  it("maps 422 detail entries onto known fields", () => {
    const err = new ApiError(422, "hire_date: Input should be a valid date", [
      { loc: ["body", "hire_date"], msg: "Input should be a valid date" },
      { loc: ["body", "user_id"], msg: "Input should be a valid UUID" },
    ]);
    const parsed = parseFormError(err, ["hire_date", "user_id"]);
    expect(parsed.fields).toEqual({
      hire_date: "Input should be a valid date",
      user_id: "Input should be a valid UUID",
    });
    expect(parsed.message).toBeNull();
  });

  it("routes unmapped 422 fields into the banner message", () => {
    const err = new ApiError(422, "…", [
      { loc: ["body", "salary"], msg: "Input should be a valid integer" },
    ]);
    const parsed = parseFormError(err, ["title"]);
    expect(parsed.fields).toEqual({});
    expect(parsed.message).toBe("salary: Input should be a valid integer");
  });

  it("passes 409 conflict strings through as the banner message", () => {
    const err = new ApiError(
      409,
      "Position with this title already exists",
      "Position with this title already exists",
    );
    const parsed = parseFormError(err, ["title"]);
    expect(parsed.message).toBe("Position with this title already exists");
    expect(parsed.fields).toEqual({});
  });

  it("falls back to a generic message for unknown errors", () => {
    expect(parseFormError("boom").message).toBe("Request failed");
    expect(parseFormError(new Error("network down")).message).toBe(
      "network down",
    );
  });
});
