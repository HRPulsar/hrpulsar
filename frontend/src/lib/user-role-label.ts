// HRP-196: resolves the single role shown in the sidebar footer.
//
// `user.roles` is an unordered many-to-many list, so reading `roles[0]`
// was a coin flip: a user promoted Employee -> Manager holds BOTH codes
// afterwards, and Postgres commonly returned `employee` first — the
// footer kept showing "Employee" for a working manager. Resolution now
// follows a fixed precedence, strongest role first.
//
// `employee` is deliberately NOT part of the ladder: it is the weakest
// role every account carries, so it must lose to anything else the user
// holds — including roles this ladder does not know (seeded `recruiter` /
// `hiring_manager`, or a tenant-custom role). It is the last resort only.
//
// An empty list still resolves to `employee` so the footer is never blank
// (the backend also re-adds the baseline role on downgrade; this is the
// display-side belt-and-braces for sessions loaded before that fix).

/**
 * Strongest first, and `employee` is excluded on purpose — see above.
 * Codes outside this list are ranked above `employee` but below these.
 */
export const ROLE_PRECEDENCE = [
  "platform_admin",
  "admin",
  "hr",
  "manager",
] as const;

export const FALLBACK_ROLE_CODE = "employee";

/** System RBAC codes localize via the catalog (namespace `sidebar`). */
export const SYSTEM_ROLE_KEYS: Record<string, string> = {
  platform_admin: "rolePlatformAdmin",
  admin: "roleAdmin",
  hr: "roleHr",
  manager: "roleManager",
  employee: "roleEmployee",
};

/**
 * Pick the one role code to display, in three tiers:
 *   1. a known strong role, strongest first;
 *   2. otherwise any role that is not the `employee` baseline — this
 *      covers seeded roles missing from the ladder (`recruiter`,
 *      `hiring_manager`) and tenant-custom roles alike;
 *   3. otherwise `employee`, including for an empty list, so the footer
 *      never renders blank.
 */
export function resolveDisplayRoleCode(
  roles: readonly string[] | null | undefined,
): string {
  if (!roles || roles.length === 0) return FALLBACK_ROLE_CODE;
  for (const code of ROLE_PRECEDENCE) {
    if (roles.includes(code)) return code;
  }
  const other = roles.find((code) => code && code !== FALLBACK_ROLE_CODE);
  return other || FALLBACK_ROLE_CODE;
}

/**
 * Human label for the resolved role. System roles go through the message
 * catalog; tenant-created custom roles have no stable key and render their
 * code prettified verbatim.
 */
export function resolveRoleLabel(
  roles: readonly string[] | null | undefined,
  translate: (key: string) => string,
): string {
  const code = resolveDisplayRoleCode(roles);
  const key = SYSTEM_ROLE_KEYS[code];
  return key ? translate(key) : code.replace(/_/g, " ");
}
