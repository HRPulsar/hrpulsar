import { RequireRecruitmentSettings } from "./gates";

// HRP-1045: the settings are no longer the admin role's alone — each tab
// follows the audience its API already admits (see gates.tsx). The outer
// layout only asks that at least one tab is reachable; the tabs gate
// themselves.
export default function RecruitmentSettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <RequireRecruitmentSettings>{children}</RequireRecruitmentSettings>;
}
