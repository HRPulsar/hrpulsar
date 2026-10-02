import { RequireRole } from "@/components/require-role";

// HRP-830: the recruitment settings are the admin role's - every write
// behind them asks for it (the scales also take `manage`), and the tab
// that leads here is shown to the admin only.
export default function RecruitmentSettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <RequireRole admin>{children}</RequireRole>;
}
