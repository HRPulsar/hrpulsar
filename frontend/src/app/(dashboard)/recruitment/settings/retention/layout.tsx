import { RequireAdminOrHr } from "../gates";

// HRP-1045: GET /recruitment/settings/retention answers the admin or hr
// role; saving stays the admin role's (the page hides the Save button).
export default function RetentionSettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <RequireAdminOrHr>{children}</RequireAdminOrHr>;
}
