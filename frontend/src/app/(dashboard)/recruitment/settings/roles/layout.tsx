import { RequireAdminOrHr } from "../gates";

// HRP-1045: GET /recruitment/settings/roles answers the admin or hr role;
// the page is read-only by nature.
export default function RolesSettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <RequireAdminOrHr>{children}</RequireAdminOrHr>;
}
