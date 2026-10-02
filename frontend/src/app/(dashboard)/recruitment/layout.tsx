import { RecruitmentOnboardingBanner } from "@/components/recruitment/onboarding-banner";

// HRP-830: the recruitment subtree follows its section - `SectionGate` in
// the dashboard layout bounces a caller without `view` on it before any
// child request goes out (it used to be `RequireRole recruit`, HRP-622).
export default function RecruitmentLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      <RecruitmentOnboardingBanner />
      {children}
    </>
  );
}
