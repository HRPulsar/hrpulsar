import { RecruitmentOnboardingBanner } from "@/components/recruitment/onboarding-banner";

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
