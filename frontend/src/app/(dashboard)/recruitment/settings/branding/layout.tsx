import { RequireReadsHiringSettings } from "../gates";

// HRP-1045: GET /recruitment/settings/branding answers `manage` on
// recruitment or the admin role (`reads_hiring_settings`); saving stays
// the admin role's (the page hides the Save button).
export default function BrandingSettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <RequireReadsHiringSettings>{children}</RequireReadsHiringSettings>;
}
