/**
 * Split a single free-text name into the first/last pair our forms collect.
 *
 * Invitations carry one `name` field (what the inviter typed), while the
 * accept form asks for a first and a last name (HRP-435). The split is on the
 * first whitespace run: everything before it is the first name, the remainder
 * — middle names, particles, multi-word surnames — stays together as the last
 * name. A single-word name pre-fills only the first name.
 *
 * Presentation-only: both fields stay editable, so a wrong guess costs the
 * person one keystroke rather than a wrong account.
 */
export function splitFullName(name: string): {
  firstName: string;
  lastName: string;
} {
  const trimmed = (name ?? "").trim();
  if (!trimmed) return { firstName: "", lastName: "" };

  const separator = trimmed.search(/\s/);
  if (separator === -1) return { firstName: trimmed, lastName: "" };

  return {
    firstName: trimmed.slice(0, separator),
    lastName: trimmed.slice(separator).trim(),
  };
}
