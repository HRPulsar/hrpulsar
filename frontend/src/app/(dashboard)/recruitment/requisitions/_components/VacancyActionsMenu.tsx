"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  Archive,
  ArchiveRestore,
  CircleCheck,
  CircleX,
  MoreVertical,
  Pause,
  Pencil,
  Play,
  Send,
  Trash2,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { api } from "@/lib/api";
import type { Vacancy } from "@/lib/types";
import {
  VACANCY_STATUS_COMMANDS,
  vacancyLocks,
  type VacancyStatusCommand,
} from "@/lib/vacancy-status";
import { toast } from "sonner";
import { VacancyArchiveDialog } from "./VacancyArchiveDialog";
import { VacancyDeleteDialog } from "./VacancyDeleteDialog";
import { VacancyStatusDialog } from "./VacancyStatusDialog";

// HRP-427 / HRP-836: label and icon of each lifecycle command.
const COMMAND_ITEMS: Record<
  VacancyStatusCommand,
  { labelKey: string; icon: LucideIcon }
> = {
  publish: { labelKey: "actionPublish", icon: Send },
  pause: { labelKey: "actionPause", icon: Pause },
  reopen: { labelKey: "actionReopen", icon: Play },
  close: { labelKey: "actionCloseVacancy", icon: CircleCheck },
  cancel: { labelKey: "actionCancelVacancy", icon: CircleX },
};

type Props = {
  vacancy: Vacancy;
  onChanged?: () => void;
};

export function VacancyActionsMenu({ vacancy, onChanged }: Props) {
  const t = useTranslations("recruitment");
  const router = useRouter();
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [command, setCommand] = useState<VacancyStatusCommand | null>(null);

  const isArchived = !!vacancy.archived_at;
  // HRP-836: a closed or cancelled vacancy is read-only — no Edit, and no
  // status command leads anywhere from there.
  const canEdit = !isArchived && !vacancyLocks(vacancy.status, "vacancy");
  const commands = isArchived
    ? []
    : (VACANCY_STATUS_COMMANDS[vacancy.status] ?? []);
  const candidatesCount = vacancy.candidates_count ?? 0;
  const canDelete =
    vacancy.status === "draft" && candidatesCount === 0 && !vacancy.has_profile;

  async function handleRestore() {
    try {
      await api.post(`/recruitment/vacancies/${vacancy.id}/restore`);
      toast.success(t("vacancyToastRestored"));
      onChanged?.();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("vacancyRestoreFailed"));
    }
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t("vacancyActionsAria")}
              data-testid={`vacancy-actions-menu-trigger-${vacancy.id}`}
              onClick={(e) => e.stopPropagation()}
            />
          }
        >
          <MoreVertical />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {canEdit && (
            <DropdownMenuItem
              data-testid={`vacancy-actions-menu-edit-${vacancy.id}`}
              onClick={(e) => {
                e.stopPropagation();
                router.push(`/recruitment/requisitions/${vacancy.id}/edit`);
              }}
            >
              <Pencil />
              {t("actionEdit")}
            </DropdownMenuItem>
          )}
          {commands.map((cmd) => {
            const { labelKey, icon: Icon } = COMMAND_ITEMS[cmd];
            return (
              <DropdownMenuItem
                key={cmd}
                data-testid={`vacancy-actions-menu-${cmd}-${vacancy.id}`}
                onClick={(e) => {
                  e.stopPropagation();
                  setCommand(cmd);
                }}
              >
                <Icon />
                {t(labelKey)}
              </DropdownMenuItem>
            );
          })}
          {!isArchived && (
            <DropdownMenuItem
              data-testid={`vacancy-actions-menu-archive-${vacancy.id}`}
              onClick={(e) => {
                e.stopPropagation();
                setArchiveOpen(true);
              }}
            >
              <Archive />
              {t("actionArchive")}
            </DropdownMenuItem>
          )}
          {isArchived && (
            <DropdownMenuItem
              data-testid={`vacancy-actions-menu-restore-${vacancy.id}`}
              onClick={(e) => {
                e.stopPropagation();
                void handleRestore();
              }}
            >
              <ArchiveRestore />
              {t("actionRestore")}
            </DropdownMenuItem>
          )}
          {canDelete && (
            <DropdownMenuItem
              variant="destructive"
              data-testid={`vacancy-actions-menu-delete-${vacancy.id}`}
              onClick={(e) => {
                e.stopPropagation();
                setDeleteOpen(true);
              }}
            >
              <Trash2 />
              {t("vacancyDeletePermanently")}
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      <VacancyArchiveDialog
        vacancy={vacancy}
        open={archiveOpen}
        onOpenChange={setArchiveOpen}
        onArchived={onChanged}
      />
      <VacancyDeleteDialog
        vacancy={vacancy}
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        onDeleted={onChanged}
      />
      <VacancyStatusDialog
        vacancy={vacancy}
        command={command}
        onOpenChange={(open) => {
          if (!open) setCommand(null);
        }}
        onChanged={onChanged}
      />
    </>
  );
}
