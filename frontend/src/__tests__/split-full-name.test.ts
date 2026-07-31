import { describe, it, expect } from "vitest";
import { splitFullName } from "@/lib/name";

// HRP-435: the accept-invitation form pre-fills from the invitation's single
// `name` field.
describe("splitFullName", () => {
  it("splits on the first space", () => {
    expect(splitFullName("Anna Schmidt")).toEqual({
      firstName: "Anna",
      lastName: "Schmidt",
    });
  });

  it("keeps everything after the first space as the last name", () => {
    expect(splitFullName("Maria von der Leyen")).toEqual({
      firstName: "Maria",
      lastName: "von der Leyen",
    });
  });

  it("puts a single-word name into the first name", () => {
    expect(splitFullName("Cher")).toEqual({ firstName: "Cher", lastName: "" });
  });

  it("trims surrounding and repeated whitespace", () => {
    expect(splitFullName("  Anna   Schmidt  ")).toEqual({
      firstName: "Anna",
      lastName: "Schmidt",
    });
  });

  it("handles tabs and newlines as separators", () => {
    expect(splitFullName("Anna\tSchmidt")).toEqual({
      firstName: "Anna",
      lastName: "Schmidt",
    });
  });

  it("returns empty fields for an empty or whitespace-only name", () => {
    expect(splitFullName("")).toEqual({ firstName: "", lastName: "" });
    expect(splitFullName("   ")).toEqual({ firstName: "", lastName: "" });
  });

  it("does not treat an email as a name split", () => {
    expect(splitFullName("anna@example.com")).toEqual({
      firstName: "anna@example.com",
      lastName: "",
    });
  });
});
