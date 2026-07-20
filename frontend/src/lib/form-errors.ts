import { ApiError } from "@/lib/api";

/**
 * Parsed backend mutation error for modal forms (HRP-399).
 *
 * FastAPI 422 validation errors carry a `detail` array with per-field `loc`
 * entries; conflicts (409) and other HTTPExceptions carry a string detail.
 * Modals map known fields to inline messages and surface the rest in a
 * visible in-modal banner instead of a silent toast.
 */
export interface FormErrorState {
  /** Non-field message for the modal banner (conflicts, unmapped fields). */
  message: string | null;
  /** Per-field messages keyed by the backend schema field name. */
  fields: Record<string, string>;
}

export const EMPTY_FORM_ERROR: FormErrorState = { message: null, fields: {} };

interface ValidationItem {
  loc?: unknown;
  msg?: unknown;
}

function fieldFromLoc(loc: unknown): string | null {
  if (!Array.isArray(loc)) return null;
  const parts = loc
    .filter((part) => typeof part === "string" && part !== "body")
    .map(String);
  return parts.length > 0 ? parts.join(".") : null;
}

export function parseFormError(
  err: unknown,
  knownFields: string[] = [],
): FormErrorState {
  if (err instanceof ApiError && Array.isArray(err.detail)) {
    const fields: Record<string, string> = {};
    const rest: string[] = [];
    for (const item of err.detail as ValidationItem[]) {
      const field = fieldFromLoc(item.loc);
      const msg = typeof item.msg === "string" ? item.msg : "Invalid value";
      if (field && knownFields.includes(field)) {
        fields[field] = msg;
      } else {
        rest.push(field ? `${field}: ${msg}` : msg);
      }
    }
    if (rest.length === 0 && Object.keys(fields).length === 0) {
      return { message: err.message || "Request failed", fields };
    }
    return { message: rest.length > 0 ? rest.join("\n") : null, fields };
  }
  if (err instanceof Error && err.message) {
    return { message: err.message, fields: {} };
  }
  return { message: "Request failed", fields: {} };
}
