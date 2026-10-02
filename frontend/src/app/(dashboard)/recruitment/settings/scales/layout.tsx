import { RequireSection } from "@/components/require-section";

// HRP-830: the hiring-round scales are written at `manage` on recruitment,
// on top of the admin role the settings ask for - an admin the tenant
// left at `view` gets the bounce rather than buttons that answer 403.
export default function ScaleSettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <RequireSection code="recruitment" level="manage">
      {children}
    </RequireSection>
  );
}
