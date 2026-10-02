import { RequireSection } from "@/components/require-section";

// HRP-830: every call this page makes writes - `manage` on recruitment.
export default function RequireHiringLayout({
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
