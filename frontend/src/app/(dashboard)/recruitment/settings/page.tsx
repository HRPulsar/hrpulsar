import Link from "next/link";
import { useTranslations } from "next-intl";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { RecruitmentBreadcrumbs, RecruitmentTabs } from "@/components/recruitment";
import {
  Activity,
  FileText,
  Globe2,
  Image as ImageIcon,
  ListChecks,
  Mic,
  Ruler,
  ScrollText,
  ShieldCheck,
  UsersRound,
} from "lucide-react";

// HRP-476: the tile copy lives in the `recruitment` i18n namespace — the
// static list only owns the route → icon → key relation.
const TILES = [
  {
    href: "/recruitment/settings/scales",
    labelKey: "settingsTileScales",
    descriptionKey: "settingsTileScalesDesc",
    icon: Ruler,
    testId: "rec-settings-card-scales",
  },
  {
    href: "/recruitment/settings/llm-providers",
    labelKey: "settingsTileLlm",
    descriptionKey: "settingsTileLlmDesc",
    icon: Globe2,
    testId: "rec-settings-card-llm",
  },
  {
    href: "/recruitment/settings/transcription-providers",
    labelKey: "settingsTileStt",
    descriptionKey: "settingsTileSttDesc",
    icon: Mic,
    testId: "rec-settings-card-stt",
  },
  {
    href: "/recruitment/settings/branding",
    labelKey: "settingsTileBranding",
    descriptionKey: "settingsTileBrandingDesc",
    icon: ImageIcon,
    testId: "rec-settings-card-branding",
  },
  {
    href: "/recruitment/settings/retention",
    labelKey: "settingsTileRetention",
    descriptionKey: "settingsTileRetentionDesc",
    icon: ShieldCheck,
    testId: "rec-settings-card-retention",
  },
  {
    href: "/recruitment/settings/roles",
    labelKey: "settingsTileRoles",
    descriptionKey: "settingsTileRolesDesc",
    icon: UsersRound,
    testId: "rec-settings-card-roles",
  },
  {
    href: "/recruitment/settings/report-templates",
    labelKey: "settingsTileReportTemplates",
    descriptionKey: "settingsTileReportTemplatesDesc",
    icon: FileText,
    testId: "rec-settings-card-report-templates",
  },
  {
    href: "/recruitment/settings/consent-templates",
    labelKey: "settingsTileConsentTemplates",
    descriptionKey: "settingsTileConsentTemplatesDesc",
    icon: ScrollText,
    testId: "rec-settings-card-consent-templates",
  },
  {
    href: "/recruitment/audit-log",
    labelKey: "settingsTileAudit",
    descriptionKey: "settingsTileAuditDesc",
    icon: Activity,
    testId: "rec-settings-card-audit",
  },
];

export default function RecruitmentSettingsHubPage() {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  return (
    <div className="space-y-5" data-testid="recruitment-settings-hub">
      <RecruitmentBreadcrumbs segments={[{ label: tc("settings") }]} />
      <RecruitmentTabs />
      <header>
        <h1 className="text-xl font-semibold tracking-tight">
          {t("settingsTitle")}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("settingsDescription")}
        </p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {TILES.map((tile) => {
          const Icon = tile.icon;
          return (
            <Card
              key={tile.href}
              className="transition-colors hover:border-[var(--rec-accent,theme(colors.cyan.500))]"
              data-testid={tile.testId}
            >
              <CardHeader className="flex-row items-start gap-3 space-y-0 pb-2">
                <div className="rounded-lg bg-cyan-50 p-2 text-cyan-600 dark:bg-cyan-950/40 dark:text-cyan-300">
                  <Icon className="size-4" />
                </div>
                <div className="space-y-0.5">
                  <CardTitle className="text-sm">{t(tile.labelKey)}</CardTitle>
                  <CardDescription className="text-xs">
                    {t(tile.descriptionKey)}
                  </CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                <Link
                  href={tile.href}
                  className="text-xs font-medium text-cyan-700 underline-offset-2 hover:underline"
                >
                  {t("settingsOpenLink")}
                </Link>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <Card className="bg-muted/40">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <ListChecks className="size-4" />
            {t("settingsWhatElseTitle")}
          </CardTitle>
        </CardHeader>
        <CardContent className="text-xs text-muted-foreground">
          {t("settingsWhatElseBody")}
        </CardContent>
      </Card>
    </div>
  );
}
