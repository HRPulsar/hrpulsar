import { RequireReadsHiringSettings } from "../gates";

// HRP-1045: GET /recruitment/consent-templates answers `manage` on
// recruitment or the admin role (`reads_hiring_settings`); creating and
// editing templates stays the admin role's (the page hides those controls).
export default function ConsentTemplatesLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <RequireReadsHiringSettings>{children}</RequireReadsHiringSettings>;
}
