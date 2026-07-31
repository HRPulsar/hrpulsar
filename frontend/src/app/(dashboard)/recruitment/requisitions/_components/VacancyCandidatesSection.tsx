"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Settings2, UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  AddCandidateDialog,
  VacancyCandidatesTable,
  VacancyStagesDrawer,
} from "@/components/recruitment";

interface VacancyCandidatesSectionProps {
  vacancyId: string;
  count: number;
}

export function VacancyCandidatesSection({
  vacancyId,
  count,
}: VacancyCandidatesSectionProps) {
  const t = useTranslations("recruitment");
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [stagesOpen, setStagesOpen] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const [currentCount, setCurrentCount] = useState(count);

  const triggerReload = useCallback(() => {
    setReloadToken((n) => n + 1);
  }, []);

  return (
    <Card data-testid="vacancy-section-candidates" id="candidates">
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle>
          {t("candidatesTitle")}{" "}
          <span className="text-sm font-normal text-muted-foreground">
            ({currentCount})
          </span>
        </CardTitle>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => setStagesOpen(true)}
            data-testid="vacancy-stage-manage-btn"
          >
            <Settings2 className="mr-1 size-4" /> {t("vacancyManageStages")}
          </Button>
          <Button
            size="sm"
            onClick={() => setOpen(true)}
            data-testid="vacancy-section-candidates-add-btn"
          >
            <UserPlus className="mr-1 size-4" /> {t("candidateAddButton")}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <VacancyCandidatesTable
          vacancyId={vacancyId}
          reloadToken={reloadToken}
          onRowCountChange={setCurrentCount}
        />
      </CardContent>

      <AddCandidateDialog
        vacancyId={vacancyId}
        open={open}
        onOpenChange={setOpen}
        onCandidatesChanged={triggerReload}
        onManualCreated={(candidateId) =>
          router.push(`/recruitment/candidates/${candidateId}`)
        }
      />
      <VacancyStagesDrawer
        vacancyId={vacancyId}
        open={stagesOpen}
        onOpenChange={setStagesOpen}
        onSaved={triggerReload}
      />
    </Card>
  );
}
