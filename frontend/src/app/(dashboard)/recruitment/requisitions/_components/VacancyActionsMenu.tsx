"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Archive,
  ArchiveRestore,
  MoreVertical,
  Pencil,
  Trash2,
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
import { toast } from "sonner";
import { VacancyArchiveDialog } from "./VacancyArchiveDialog";
import { VacancyDeleteDialog } from "./VacancyDeleteDialog";

type Props = {
  vacancy: Vacancy;
  onChanged?: () => void;
};

export function VacancyActionsMenu({ vacancy, onChanged }: Props) {
  const router = useRouter();
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const isArchived = !!vacancy.archived_at;
  const candidatesCount = vacancy.candidates_count ?? 0;
  const canDelete =
    vacancy.status === "draft" && candidatesCount === 0 && !vacancy.has_profile;

  async function handleRestore() {
    try {
      await api.post(`/recruitment/vacancies/${vacancy.id}/restore`);
      toast.success("Vacancy restored");
      onChanged?.();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to restore");
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
              aria-label="Vacancy actions"
              data-testid={`vacancy-actions-menu-trigger-${vacancy.id}`}
              onClick={(e) => e.stopPropagation()}
            />
          }
        >
          <MoreVertical />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {!isArchived && (
            <DropdownMenuItem
              data-testid={`vacancy-actions-menu-edit-${vacancy.id}`}
              onClick={(e) => {
                e.stopPropagation();
                router.push(`/recruitment/requisitions/${vacancy.id}/edit`);
              }}
            >
              <Pencil />
              Edit
            </DropdownMenuItem>
          )}
          {!isArchived && (
            <DropdownMenuItem
              data-testid={`vacancy-actions-menu-archive-${vacancy.id}`}
              onClick={(e) => {
                e.stopPropagation();
                setArchiveOpen(true);
              }}
            >
              <Archive />
              Archive
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
              Restore
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
              Delete permanently
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
    </>
  );
}
