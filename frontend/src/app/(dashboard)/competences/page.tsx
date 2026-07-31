"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import {
  DndContext,
  type DragEndEvent,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { GripVertical } from "lucide-react";
import { useTranslations } from "next-intl";
import { ApiError, api } from "@/lib/api";
import { getBrandName } from "@/lib/brand";
import { visibleCompetenceTypes } from "@/lib/competence-type-filter";
import { dictionaryItemLabel } from "@/lib/reference-labels";
import {
  isActiveSessionConflict,
  type ActiveSessionRef,
} from "@/lib/active-ai-session-route";
import { ActiveSessionConflictDialog } from "@/components/competence-generation/ActiveSessionConflictDialog";
import type { CompetenceGroupTree, DictionaryItem } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { IndicatorsEditor } from "@/components/competence/indicators-editor";
import { TreeExpandControls } from "@/components/ui/tree-expand-controls";
import { usePermissions } from "@/hooks/use-permissions";
import { useTreeExpansion } from "@/hooks/use-tree-expansion";
import { toast } from "sonner";
import {
  CheckCircle2,
  CircleSlash,
  ExternalLink,
  Eye,
  EyeOff,
  Link2,
  Lock,
  MoreHorizontal,
  Pencil,
  Plus,
  Sparkles,
  Star,
  Trash2,
} from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import { GenerationStatusButton } from "@/components/competence-generation/GenerationStatusButton";
import { GenerationDrawer } from "@/components/competence-generation/GenerationDrawer";
import { useGenerationSession } from "@/hooks/use-generation-session";
import { GenerationConfirmDialog } from "@/components/competence-generation/GenerationConfirmDialog";
import { ActiveAiSessionBadge } from "@/components/competence-generation/ActiveAiSessionBadge";
import {
  competenceGenerationApi,
  SessionScope,
} from "@/lib/api/competence-generation";
import {
  activeAiSessionsKey,
  useActiveAiSessions,
  type ActiveAiSession,
} from "@/hooks/use-active-ai-sessions";
import {
  invalidateCompetenceTree,
  useCompetenceTree,
} from "@/hooks/use-competence-tree";

interface CompetenceItem {
  id: string;
  title: string;
  description: string | null;
  group_id: string;
  competence_type_id: string | null;
  tenant_id: string | null;
  is_active: boolean;
  is_published: boolean;
  is_origin: boolean;
  is_used: boolean;
}

const emptyGroupForm = {
  title: "",
  description: "",
  parent_id: "",
  sort_index: 0,
  is_active: true,
};
const emptyCompForm = { title: "", description: "", group_id: "", competence_type_id: "" };

function GroupNode({
  group,
  depth = 0,
  onEditGroup,
  onDeleteGroup,
  onDeactivateGroup,
  onAddChild,
  onAddCompetence,
  onBulkAddCompetences,
  onEditCompetence,
  onDeleteCompetence,
  onTogglePublishCompetence,
  onGenerateGroup,
  onGenerateIndicators,
  generationLocked,
  generationLockedTargetId,
  activeSessionsMap,
  onOpenActiveSession,
  isExpanded,
  onToggleExpand,
}: {
  group: CompetenceGroupTree;
  depth?: number;
  onEditGroup: (g: CompetenceGroupTree) => void;
  onDeleteGroup: (g: CompetenceGroupTree) => void;
  onDeactivateGroup: (g: CompetenceGroupTree) => void;
  onAddChild: (parentId: string) => void;
  onAddCompetence: (groupId: string) => void;
  onBulkAddCompetences: (group: CompetenceGroupTree) => void;
  onEditCompetence: (c: CompetenceItem) => void;
  onDeleteCompetence: (c: CompetenceItem) => void;
  onTogglePublishCompetence: (c: CompetenceItem) => void;
  onGenerateGroup: (g: CompetenceGroupTree) => void;
  onGenerateIndicators: (c: CompetenceItem) => void;
  generationLocked: boolean;
  generationLockedTargetId: string | null;
  activeSessionsMap: Map<string, ActiveAiSession[]>;
  onOpenActiveSession: (sessionId: string) => void;
  // HRP-109: expansion state lives in the page so Expand all / Collapse all
  // buttons can flip every group at once.
  isExpanded: (groupId: string) => boolean;
  onToggleExpand: (groupId: string) => void;
}) {
  const t = useTranslations("competences");
  const isOriginGroup = group.tenant_id === null;
  const expanded = isExpanded(group.id);
  const hasChildren =
    group.children.length > 0 || group.competences.length > 0;
  const groupSessions =
    activeSessionsMap.get(activeAiSessionsKey("group", group.id)) ?? [];
  const isLitUp = groupSessions.length > 0;

  const { setNodeRef: dropRef, isOver: isOverDrop } = useDroppable({
    id: `dropgroup-${group.id}`,
    data: { kind: "group", groupId: group.id, isOrigin: isOriginGroup },
  });

  const {
    setNodeRef: dragRef,
    attributes: dragAttrs,
    listeners: dragListeners,
  } = useDraggable({
    id: `draggroup-${group.id}`,
    data: { kind: "group", groupId: group.id, isOrigin: isOriginGroup },
    disabled: isOriginGroup,
  });

  return (
    <div
      ref={dropRef}
      data-testid={`competences-group-${group.id}`}
      className={
        isOverDrop
          ? "rounded-md ring-2 ring-primary/40 transition"
          : undefined
      }
    >
      <div
        className={`group flex w-full items-center gap-2 rounded-md px-3 py-2 transition-colors ${
          isLitUp
            ? "bg-primary/10 ring-1 ring-primary/30 hover:bg-primary/15"
            : "hover:bg-muted"
        }`}
        style={{ paddingLeft: `${depth * 24 + 12}px` }}
      >
        <button
          ref={dragRef}
          {...dragAttrs}
          {...dragListeners}
          type="button"
          aria-label={t("dragGroupAria")}
          data-testid={`competences-group-${group.id}-handle`}
          className={`text-muted-foreground ${
            isOriginGroup ? "opacity-30 cursor-not-allowed" : "cursor-grab"
          }`}
          title={
            isOriginGroup ? t("originGroupCannotMove") : t("dragToMove")
          }
          disabled={isOriginGroup}
          onClick={(e) => e.preventDefault()}
        >
          <GripVertical className="h-3.5 w-3.5" />
        </button>
        <button
          data-testid={`competences-group-${group.id}-toggle`}
          onClick={() => onToggleExpand(group.id)}
          className="flex flex-1 items-center gap-2 text-left"
        >
          {hasChildren ? (
            <svg
              className={`h-4 w-4 text-muted-foreground transition-transform ${expanded ? "rotate-90" : ""}`}
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={1.5}
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="m8.25 4.5 7.5 7.5-7.5 7.5"
              />
            </svg>
          ) : (
            <div className="w-4" />
          )}
          <svg
            className="h-4 w-4 text-muted-foreground"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={1.5}
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M2.25 12.75V12A2.25 2.25 0 0 1 4.5 9.75h15A2.25 2.25 0 0 1 21.75 12v.75m-8.69-6.44-2.12-2.12a1.5 1.5 0 0 0-1.061-.44H4.5A2.25 2.25 0 0 0 2.25 6v12a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9a2.25 2.25 0 0 0-2.25-2.25h-5.379a1.5 1.5 0 0 1-1.06-.44Z"
            />
          </svg>
          <span className="text-sm font-medium">{group.title}</span>
          {isOriginGroup && (
            <Lock
              className="h-3 w-3 text-muted-foreground"
              data-testid={`competences-group-${group.id}-origin-icon`}
            />
          )}
          {!group.is_active && (
            <Badge
              variant="outline"
              data-testid={`competences-group-${group.id}-hidden-badge`}
              className="text-[10px]"
            >
              {t("badgeHidden")}
            </Badge>
          )}
          <span
            data-testid={`competences-group-${group.id}-count`}
            className="ml-auto text-xs text-muted-foreground"
          >
            {t("groupCompetencesCount", { count: group.competences.length })}
          </span>
        </button>
        {isLitUp && (
          <ActiveAiSessionBadge
            sessions={groupSessions}
            onOpen={onOpenActiveSession}
            testIdSuffix={`group-${group.id}`}
          />
        )}
        {!isOriginGroup && (
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  data-testid={`competences-group-${group.id}-btn-bulk-add`}
                  aria-label={t("addCompetences")}
                  size="icon-xs"
                  variant="ghost"
                  className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity"
                  onClick={() => onBulkAddCompetences(group)}
                />
              }
            >
              <Plus className="h-4 w-4" />
            </TooltipTrigger>
            <TooltipContent side="top">{t("addCompetences")}</TooltipContent>
          </Tooltip>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger data-testid={`competences-group-${group.id}-actions`} render={<Button variant="ghost" size="icon-xs" className="opacity-0 group-hover:opacity-100 transition-opacity" />}>
            <MoreHorizontal className="h-4 w-4" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-[12rem]">
            <DropdownMenuItem data-testid={`competences-group-${group.id}-btn-add-competence`} onClick={() => onAddCompetence(group.id)} className="whitespace-nowrap">
              <Star className="mr-2 h-4 w-4" />
              {t("addCompetence")}
            </DropdownMenuItem>
            <DropdownMenuItem data-testid={`competences-group-${group.id}-btn-add-subgroup`} onClick={() => onAddChild(group.id)} className="whitespace-nowrap">
              <Plus className="mr-2 h-4 w-4" />
              {t("addSubgroup")}
            </DropdownMenuItem>
            {generationLocked ? (
              <Tooltip>
                <TooltipTrigger
                  render={
                    <div
                      data-testid={
                        group.competences.length === 0
                          ? `compgen-group-menu-fill-${group.id}`
                          : `compgen-group-menu-extend-${group.id}`
                      }
                    />
                  }
                >
                  <DropdownMenuItem disabled className="whitespace-nowrap">
                    <Sparkles className="mr-2 h-4 w-4" />
                    {group.competences.length === 0
                      ? t("fillGroupWithAi")
                      : t("extendGroupWithAi")}
                  </DropdownMenuItem>
                </TooltipTrigger>
                <TooltipContent side="left">
                  {t("activeSessionHint")}
                </TooltipContent>
              </Tooltip>
            ) : (
              <DropdownMenuItem
                data-testid={
                  group.competences.length === 0
                    ? `compgen-group-menu-fill-${group.id}`
                    : `compgen-group-menu-extend-${group.id}`
                }
                onClick={() => onGenerateGroup(group)}
                className="whitespace-nowrap"
              >
                <Sparkles className="mr-2 h-4 w-4" />
                {group.competences.length === 0
                  ? t("fillGroupWithAi")
                  : t("extendGroupWithAi")}
              </DropdownMenuItem>
            )}
            <DropdownMenuItem data-testid={`competences-group-${group.id}-btn-edit`} onClick={() => onEditGroup(group)} className="whitespace-nowrap">
              <Pencil className="mr-2 h-4 w-4" />
              {t("editGroup")}
            </DropdownMenuItem>
            {!isOriginGroup && (
              <DropdownMenuItem
                data-testid={`competences-group-${group.id}-btn-deactivate`}
                onClick={() => onDeactivateGroup(group)}
                className="whitespace-nowrap"
              >
                {group.is_active ? (
                  <>
                    <EyeOff className="mr-2 h-4 w-4" />
                    {t("hideFromUsers")}
                  </>
                ) : (
                  <>
                    <Eye className="mr-2 h-4 w-4" />
                    {t("showToUsers")}
                  </>
                )}
              </DropdownMenuItem>
            )}
            {/* HRP-118: hide Delete when the group is wired into other services. */}
            {!group.is_used && (
              <DropdownMenuItem
                data-testid={`competences-group-${group.id}-btn-delete`}
                variant="destructive"
                onClick={() => onDeleteGroup(group)}
                disabled={isOriginGroup && !group.can_deactivate}
                className="whitespace-nowrap"
              >
                <Trash2 className="mr-2 h-4 w-4" />
                {t("deleteGroup")}
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {expanded && (
        <>
          {group.competences.map((comp) => (
            <CompetenceRow
              key={comp.id}
              comp={comp as CompetenceItem}
              depth={depth}
              generationLocked={generationLocked}
              generationLockedTargetId={generationLockedTargetId}
              onEditCompetence={onEditCompetence}
              onDeleteCompetence={onDeleteCompetence}
              onTogglePublishCompetence={onTogglePublishCompetence}
              onGenerateIndicators={onGenerateIndicators}
              activeSessionsMap={activeSessionsMap}
              onOpenActiveSession={onOpenActiveSession}
            />
          ))}
          {group.children.map((child) => (
            <GroupNode
              key={child.id}
              group={child}
              depth={depth + 1}
              onEditGroup={onEditGroup}
              onDeleteGroup={onDeleteGroup}
              onDeactivateGroup={onDeactivateGroup}
              onAddChild={onAddChild}
              onAddCompetence={onAddCompetence}
              onBulkAddCompetences={onBulkAddCompetences}
              onEditCompetence={onEditCompetence}
              onDeleteCompetence={onDeleteCompetence}
              onTogglePublishCompetence={onTogglePublishCompetence}
              onGenerateGroup={onGenerateGroup}
              onGenerateIndicators={onGenerateIndicators}
              generationLocked={generationLocked}
              generationLockedTargetId={generationLockedTargetId}
              activeSessionsMap={activeSessionsMap}
              onOpenActiveSession={onOpenActiveSession}
              isExpanded={isExpanded}
              onToggleExpand={onToggleExpand}
            />
          ))}
        </>
      )}
    </div>
  );
}

function flattenGroups(
  groups: CompetenceGroupTree[],
  depth = 0,
): (CompetenceGroupTree & { depth: number })[] {
  const result: (CompetenceGroupTree & { depth: number })[] = [];
  for (const g of groups) {
    result.push({ ...g, depth });
    if (g.children.length > 0) {
      result.push(...flattenGroups(g.children, depth + 1));
    }
  }
  return result;
}

function findCompetenceGroupId(
  groups: CompetenceGroupTree[],
  competenceId: string,
): string | null {
  for (const g of groups) {
    if (g.competences.some((c) => c.id === competenceId)) return g.id;
    const inner = findCompetenceGroupId(g.children, competenceId);
    if (inner) return inner;
  }
  return null;
}

function CompetenceRow({
  comp,
  depth,
  generationLocked,
  generationLockedTargetId,
  onEditCompetence,
  onDeleteCompetence,
  onTogglePublishCompetence,
  onGenerateIndicators,
  activeSessionsMap,
  onOpenActiveSession,
}: {
  comp: CompetenceItem;
  depth: number;
  generationLocked: boolean;
  generationLockedTargetId: string | null;
  onEditCompetence: (c: CompetenceItem) => void;
  onDeleteCompetence: (c: CompetenceItem) => void;
  // HRP-118 redo: parent flips is_published via the publish/unpublish API.
  onTogglePublishCompetence: (c: CompetenceItem) => void;
  onGenerateIndicators: (c: CompetenceItem) => void;
  activeSessionsMap: Map<string, ActiveAiSession[]>;
  onOpenActiveSession: (sessionId: string) => void;
}) {
  const t = useTranslations("competences");
  const tc = useTranslations("common");
  const compSessions =
    activeSessionsMap.get(
      activeAiSessionsKey("competence_indicators", comp.id),
    ) ?? [];
  const isLitUp = compSessions.length > 0;
  const isOriginComp = comp.tenant_id === null;
  const {
    setNodeRef: dragRef,
    attributes: dragAttrs,
    listeners: dragListeners,
  } = useDraggable({
    id: `dragcomp-${comp.id}`,
    data: { kind: "competence", competenceId: comp.id, isOrigin: isOriginComp },
    disabled: isOriginComp,
  });
  return (
    <div
      data-testid={`competences-item-${comp.id}`}
      className={`group flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors ${
        isLitUp
          ? "bg-primary/10 ring-1 ring-primary/30 text-foreground"
          : "text-muted-foreground hover:bg-muted/50"
      }`}
      style={{ paddingLeft: `${(depth + 1) * 24 + 12}px` }}
    >
      <button
        ref={dragRef}
        {...dragAttrs}
        {...dragListeners}
        type="button"
        aria-label={t("dragCompetenceAria")}
        data-testid={`competences-item-${comp.id}-handle`}
        className={`text-muted-foreground ${
          isOriginComp ? "opacity-30 cursor-not-allowed" : "cursor-grab"
        }`}
        title={
          isOriginComp ? t("originCompetenceCannotMove") : t("dragToMove")
        }
        disabled={isOriginComp}
        onClick={(e) => e.preventDefault()}
      >
        <GripVertical className="h-3.5 w-3.5" />
      </button>
      <Star className="h-3.5 w-3.5" />
      <Link
        href={`/competences/${comp.id}`}
        className="flex-1 hover:text-foreground hover:underline"
        data-testid={`competences-item-${comp.id}-link`}
      >
        {comp.title}
      </Link>
      {comp.is_published ? (
        <Tooltip>
          <TooltipTrigger
            render={
              <span
                className="inline-flex"
                tabIndex={-1}
                aria-label={t("publishedAria")}
              />
            }
          >
            <CheckCircle2
              className="h-3.5 w-3.5 text-emerald-600"
              data-testid={`competences-item-${comp.id}-published-icon`}
            />
          </TooltipTrigger>
          <TooltipContent>{t("publishedTooltip")}</TooltipContent>
        </Tooltip>
      ) : (
        <Tooltip>
          <TooltipTrigger
            render={
              <span
                className="inline-flex"
                tabIndex={-1}
                aria-label={t("notPublishedAria")}
              />
            }
          >
            <CircleSlash
              className="h-3.5 w-3.5 text-muted-foreground"
              data-testid={`competences-item-${comp.id}-unpublished-icon`}
            />
          </TooltipTrigger>
          <TooltipContent>{t("notPublishedTooltip")}</TooltipContent>
        </Tooltip>
      )}
      {isOriginComp && (
        <Tooltip>
          <TooltipTrigger
            render={
              <span
                className="inline-flex"
                tabIndex={-1}
                aria-label={t("originCompetenceAria")}
              />
            }
          >
            <Lock
              className="h-3 w-3 text-muted-foreground"
              data-testid={`competences-item-${comp.id}-origin-icon`}
            />
          </TooltipTrigger>
          <TooltipContent>
            {t("originCompetenceTooltip", { brand: getBrandName() })}
          </TooltipContent>
        </Tooltip>
      )}
      {comp.is_used && (
        <Tooltip>
          <TooltipTrigger
            render={
              <span
                className="inline-flex"
                tabIndex={-1}
                aria-label={t("inUseAria")}
              />
            }
          >
            <Link2
              className="h-3.5 w-3.5 text-muted-foreground"
              data-testid={`competences-item-${comp.id}-used-badge`}
            />
          </TooltipTrigger>
          <TooltipContent>{t("inUseTooltip")}</TooltipContent>
        </Tooltip>
      )}
      {isLitUp && (
        <ActiveAiSessionBadge
          sessions={compSessions}
          onOpen={onOpenActiveSession}
          testIdSuffix={`competence-${comp.id}`}
        />
      )}
      <DropdownMenu>
        <DropdownMenuTrigger
          data-testid={`competences-item-${comp.id}-actions`}
          render={
            <Button
              variant="ghost"
              size="icon-xs"
              className="opacity-0 group-hover:opacity-100 transition-opacity"
            />
          }
        >
          <MoreHorizontal className="h-3.5 w-3.5" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="min-w-[12rem]">
          <DropdownMenuItem
            data-testid={`competences-item-${comp.id}-btn-open`}
            onClick={() => {
              window.location.href = `/competences/${comp.id}`;
            }}
            className="whitespace-nowrap"
          >
            <ExternalLink className="mr-2 h-4 w-4" />
            {t("openDetailPage")}
          </DropdownMenuItem>
          <DropdownMenuItem
            data-testid={`competences-item-${comp.id}-btn-edit`}
            onClick={() => onEditCompetence(comp)}
            disabled={isOriginComp}
            className="whitespace-nowrap"
          >
            <Pencil className="mr-2 h-4 w-4" />
            {t("edit")}
          </DropdownMenuItem>
          {generationLocked && generationLockedTargetId !== comp.id ? (
            <Tooltip>
              <TooltipTrigger
                render={
                  <div data-testid={`compgen-competence-${comp.id}-btn-indicators`} />
                }
              >
                <DropdownMenuItem disabled className="whitespace-nowrap">
                  <Sparkles className="mr-2 h-4 w-4" />
                  {t("generateIndicatorsAi")}
                </DropdownMenuItem>
              </TooltipTrigger>
              <TooltipContent side="left">
                {t("activeSessionHint")}
              </TooltipContent>
            </Tooltip>
          ) : (
            <DropdownMenuItem
              data-testid={`compgen-competence-${comp.id}-btn-indicators`}
              onClick={() => onGenerateIndicators(comp)}
              className="whitespace-nowrap"
            >
              <Sparkles className="mr-2 h-4 w-4" />
              {t("generateIndicatorsAi")}
            </DropdownMenuItem>
          )}
          {/* HRP-118 redo: mirror the group "Hide from users / Show to
              users" toggle for the individual competence row. Origin
              competences cannot be republished by a tenant. */}
          {!isOriginComp && (
            <DropdownMenuItem
              data-testid={`competences-item-${comp.id}-btn-publish`}
              onClick={() => onTogglePublishCompetence(comp)}
              className="whitespace-nowrap"
            >
              {comp.is_published ? (
                <>
                  <EyeOff className="mr-2 h-4 w-4" />
                  {t("hideFromUsers")}
                </>
              ) : (
                <>
                  <Eye className="mr-2 h-4 w-4" />
                  {t("showToUsers")}
                </>
              )}
            </DropdownMenuItem>
          )}
          <DropdownMenuItem
            data-testid={`competences-item-${comp.id}-btn-delete`}
            variant="destructive"
            onClick={() => onDeleteCompetence(comp)}
            disabled={isOriginComp || comp.is_used}
            title={
              comp.is_used ? t("competenceUsedCannotDelete") : undefined
            }
            className="whitespace-nowrap"
          >
            <Trash2 className="mr-2 h-4 w-4" />
            {tc("delete")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

export default function CompetencesPage() {
  const t = useTranslations("competences");
  const tc = useTranslations("common");
  const tRef = useTranslations("reference");
  const { tree, loading: treeLoading } = useCompetenceTree();
  const [compTypes, setCompTypes] = useState<DictionaryItem[]>([]);
  const [auxLoading, setAuxLoading] = useState(true);
  const loading = treeLoading || auxLoading;
  // HRP-479: display-only lookup — the stored value stays the type id.
  const compTypeLabel = (typeId: string) => {
    const ct = compTypes.find((c) => c.id === typeId);
    return ct ? dictionaryItemLabel(tRef, ct) : "";
  };

  // Group dialog
  const [groupDialogOpen, setGroupDialogOpen] = useState(false);
  const [groupDialogMode, setGroupDialogMode] = useState<"create" | "edit">("create");
  const [groupForm, setGroupForm] = useState(emptyGroupForm);
  const [editingGroupId, setEditingGroupId] = useState<string | null>(null);

  // Competence dialog
  const [compDialogOpen, setCompDialogOpen] = useState(false);
  const [compDialogMode, setCompDialogMode] = useState<"create" | "edit">("create");
  // Two-step wizard for create flow: step 1 — title/description/type,
  // step 2 — group selection (and indicators editor on edit). Edit mode
  // skips the wizard entirely and shows everything inline.
  const [compStep, setCompStep] = useState<1 | 2>(1);
  const [compForm, setCompForm] = useState(emptyCompForm);
  const [editingCompId, setEditingCompId] = useState<string | null>(null);

  // HRP-108: bulk-add several competences to a group in one shot.
  const [bulkDialogOpen, setBulkDialogOpen] = useState(false);
  const [bulkTargetGroup, setBulkTargetGroup] = useState<{
    id: string;
    title: string;
  } | null>(null);
  const [bulkRows, setBulkRows] = useState<
    { title: string; description: string; competence_type_id: string }[]
  >([{ title: "", description: "", competence_type_id: "" }]);

  // Delete
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{
    type: "group" | "competence";
    id: string;
    title: string;
  } | null>(null);

  const [saving, setSaving] = useState(false);

  const { canManage } = usePermissions();

  // AI generation (CR13). HRP-122 REDO #3: the page-level Generate button's
  // session snapshot used to be a bespoke useState updated only by a WS
  // handler, so dropped compgen.session.updated pushes left the button
  // stuck on "AI generation in progress". Route through
  // useGenerationSession instead so the 5s REST polling drives the
  // button's state alongside the drawer.
  const router = useRouter();
  const searchParams = useSearchParams();
  const {
    session: activeSession,
    loading: activeSessionLoading,
    refresh: refreshActiveSession,
  } = useGenerationSession("active");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerSessionId, setDrawerSessionId] = useState<string | null>(null);
  const { byTarget: activeSessionsMap, refresh: refreshActiveSessions } =
    useActiveAiSessions();

  function openDrawerForSession(sessionId: string) {
    setDrawerSessionId(sessionId);
    setDrawerOpen(true);
  }

  function openOwnDrawer() {
    setDrawerSessionId(null);
    setDrawerOpen(true);
  }
  const [groupConfirm, setGroupConfirm] = useState<{
    open: boolean;
    scope: SessionScope;
    targetId: string | null;
    targetTitle: string | null;
  }>({ open: false, scope: "group", targetId: null, targetTitle: null });
  // HRP-168: visible conflict dialog when /sessions returns 409
  // active_session_exists. Replaces the previous silent
  // window.location.href redirect that left users wondering why nothing
  // happened after they clicked Start.
  const [conflictSession, setConflictSession] = useState<ActiveSessionRef | null>(
    null,
  );
  const [lastGenerationParams, setLastGenerationParams] = useState<{
    with_indicators: boolean;
  } | null>(null);

  async function loadAux() {
    try {
      const typesData = await api.get<DictionaryItem[]>(
        "/dictionaries/competence_type",
      );
      setCompTypes(typesData);
    } catch {
      // ignore
    } finally {
      setAuxLoading(false);
    }
  }

  async function reloadAll() {
    await Promise.all([invalidateCompetenceTree(), loadAux()]);
  }

  const dndSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  );

  async function handleDragEnd(event: DragEndEvent) {
    const active = event.active;
    const over = event.over;
    if (!active || !over) return;
    const activeData = active.data.current as
      | { kind: "group" | "competence"; isOrigin: boolean; groupId?: string; competenceId?: string }
      | undefined;
    const overData = over.data.current as
      | { kind: "group"; groupId: string; isOrigin: boolean }
      | undefined;
    if (!activeData || !overData) return;
    if (overData.kind !== "group") return;

    if (activeData.isOrigin) {
      toast.error(t("errorOriginCannotMove"));
      return;
    }
    if (activeData.kind === "competence") {
      const compId = activeData.competenceId!;
      // Don't bother the API if the user dropped the competence on the same
      // group it already lives in.
      const currentGroupId = findCompetenceGroupId(tree, compId);
      if (currentGroupId === overData.groupId) return;
      try {
        await api.post(`/competences/${compId}/move`, {
          new_group_id: overData.groupId,
          new_sort_index: 0,
        });
        toast.success(t("toastCompetenceMoved"));
        await invalidateCompetenceTree();
      } catch (err) {
        toast.error(
          err instanceof Error ? err.message : t("errorMoveCompetence"),
        );
      }
    } else if (activeData.kind === "group") {
      const grpId = activeData.groupId!;
      if (grpId === overData.groupId) return;
      // Backend rejects cycles; UI doesn't need to pre-check.
      try {
        await api.post(`/competence-groups/${grpId}/move`, {
          new_parent_id: overData.groupId,
          new_sort_index: 0,
        });
        toast.success(t("toastGroupMoved"));
        await invalidateCompetenceTree();
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t("errorMoveGroup"));
      }
    }
  }

  useEffect(() => {
    loadAux();
  }, []);

  // If we navigate here with ?compgen=open (e.g. from a notification toast),
  // pop the drawer once the active session has loaded.
  useEffect(() => {
    if (searchParams.get("compgen") === "open" && activeSession) {
      setDrawerOpen(true);
      router.replace("/competences");
    }
  }, [searchParams, activeSession, router]);

  // HRP-122 REDO #3: WS subscription + manual setActiveSession used to
  // live here. The page-level button now sources its session snapshot
  // from useGenerationSession, which already polls + listens to the
  // same WS event.

  function findGroupTitle(groupId: string): string | null {
    function visit(g: CompetenceGroupTree): string | null {
      if (g.id === groupId) return g.title;
      for (const c of g.children) {
        const r = visit(c);
        if (r) return r;
      }
      return null;
    }
    for (const g of tree) {
      const r = visit(g);
      if (r) return r;
    }
    return null;
  }

  // HRP-93: resolver feeds the AI-generation drawer header. When the user
  // launches indicator generation from this list page, target_id is a
  // competence id (not a group id) — fall back to walking the tree's
  // competences so the drawer can render a clickable competence-name link.
  function findCompetenceTitle(competenceId: string): string | null {
    function visit(g: CompetenceGroupTree): string | null {
      for (const c of g.competences) {
        if (c.id === competenceId) return c.title;
      }
      for (const child of g.children) {
        const r = visit(child);
        if (r) return r;
      }
      return null;
    }
    for (const g of tree) {
      const r = visit(g);
      if (r) return r;
    }
    return null;
  }

  const flatGroups = flattenGroups(tree);

  // Group CRUD
  function openCreateGroup(parentId?: string) {
    setGroupDialogMode("create");
    setGroupForm({
      title: "",
      description: "",
      parent_id: parentId || "",
      sort_index: 0,
      is_active: true,
    });
    setEditingGroupId(null);
    setGroupDialogOpen(true);
  }

  function openEditGroup(g: CompetenceGroupTree) {
    setGroupDialogMode("edit");
    setGroupForm({
      title: g.title,
      description: g.description || "",
      parent_id: g.parent_id || "",
      sort_index: g.sort_index,
      is_active: g.is_active,
    });
    setEditingGroupId(g.id);
    setGroupDialogOpen(true);
  }

  async function toggleGroupActive(g: CompetenceGroupTree) {
    setSaving(true);
    try {
      const path = g.is_active ? "deactivate" : "activate";
      await api.patch(`/competence-groups/${g.id}/${path}`);
      // HRP-118: matches the snack-bar copy in the spec — the deactivate case
      // explicitly tells the admin everything below is hidden too.
      toast.success(
        g.is_active ? t("toastGroupHidden") : t("toastGroupVisible"),
      );
      await invalidateCompetenceTree();
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : t("errorUpdateGroupVisibility"),
      );
    } finally {
      setSaving(false);
    }
  }

  // HRP-118 redo: mirror the group visibility toggle on individual
  // competences. Reuses the existing `/competences/{id}/publish` and
  // `/competences/{id}/unpublish` endpoints that already drive the
  // is_published flag from the competence detail page.
  async function togglePublishCompetence(c: CompetenceItem) {
    setSaving(true);
    try {
      const path = c.is_published ? "unpublish" : "publish";
      await api.post(`/competences/${c.id}/${path}`);
      toast.success(
        c.is_published
          ? t("toastCompetenceHidden")
          : t("toastCompetenceVisible"),
      );
      await invalidateCompetenceTree();
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : t("errorUpdateCompetenceVisibility"),
      );
    } finally {
      setSaving(false);
    }
  }

  async function saveGroup() {
    setSaving(true);
    try {
      const payload = { ...groupForm, parent_id: groupForm.parent_id || null };
      if (groupDialogMode === "create") {
        await api.post("/competence-groups", payload);
        toast.success(t("toastGroupCreated"));
      } else {
        await api.put(`/competence-groups/${editingGroupId}`, payload);
        toast.success(t("toastGroupUpdated"));
      }
      setGroupDialogOpen(false);
      await invalidateCompetenceTree();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorSave"));
    } finally {
      setSaving(false);
    }
  }

  // Competence CRUD
  function openCreateCompetence(groupId: string) {
    setCompDialogMode("create");
    setCompForm({ title: "", description: "", group_id: groupId, competence_type_id: "" });
    setEditingCompId(null);
    setCompStep(1);
    setCompDialogOpen(true);
  }

  function openEditCompetence(c: CompetenceItem) {
    setCompDialogMode("edit");
    setCompForm({
      title: c.title,
      description: c.description || "",
      group_id: c.group_id,
      competence_type_id: c.competence_type_id || "",
    });
    setEditingCompId(c.id);
    setCompStep(1);
    setCompDialogOpen(true);
  }

  async function saveCompetence() {
    setSaving(true);
    try {
      const payload = {
        ...compForm,
        competence_type_id: compForm.competence_type_id || null,
      };
      if (compDialogMode === "create") {
        await api.post("/competences", payload);
        toast.success(t("toastCompetenceCreated"));
      } else {
        await api.put(`/competences/${editingCompId}`, payload);
        toast.success(t("toastCompetenceUpdated"));
      }
      setCompDialogOpen(false);
      await invalidateCompetenceTree();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorSave"));
    } finally {
      setSaving(false);
    }
  }

  // HRP-108: open the bulk-add dialog seeded with a single empty row.
  function openBulkAddCompetences(group: CompetenceGroupTree) {
    setBulkTargetGroup({ id: group.id, title: group.title });
    setBulkRows([{ title: "", description: "", competence_type_id: "" }]);
    setBulkDialogOpen(true);
  }

  async function saveBulkCompetences() {
    if (!bulkTargetGroup) return;
    const items = bulkRows
      .map((row) => ({
        title: row.title.trim(),
        description: row.description.trim() || null,
        competence_type_id: row.competence_type_id || null,
      }))
      .filter((row) => row.title.length > 0);
    if (items.length === 0) {
      toast.error(t("errorBulkNeedTitle"));
      return;
    }
    setSaving(true);
    try {
      await api.post(
        `/competence-groups/${bulkTargetGroup.id}/competences/bulk`,
        { items },
      );
      toast.success(t("toastCompetencesBulkCreated", { count: items.length }));
      setBulkDialogOpen(false);
      await invalidateCompetenceTree();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorSave"));
    } finally {
      setSaving(false);
    }
  }

  // Delete
  function openDeleteGroup(g: CompetenceGroupTree) {
    setDeleteTarget({ type: "group", id: g.id, title: g.title });
    setDeleteOpen(true);
  }

  function openDeleteCompetence(c: CompetenceItem) {
    setDeleteTarget({ type: "competence", id: c.id, title: c.title });
    setDeleteOpen(true);
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setSaving(true);
    try {
      if (deleteTarget.type === "group") {
        await api.delete(`/competence-groups/${deleteTarget.id}`);
      } else {
        await api.delete(`/competences/${deleteTarget.id}`);
      }
      toast.success(t("toastDeleted"));
      setDeleteOpen(false);
      await invalidateCompetenceTree();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorDelete"));
    } finally {
      setSaving(false);
    }
  }

  // CR13 — group / competence-indicator generation handlers
  function openGenerateGroup(group: CompetenceGroupTree) {
    setGroupConfirm({
      open: true,
      scope: "group",
      targetId: group.id,
      targetTitle: group.title,
    });
  }

  function openGenerateIndicators(comp: CompetenceItem) {
    setGroupConfirm({
      open: true,
      scope: "competence_indicators",
      targetId: comp.id,
      targetTitle: comp.title,
    });
  }

  async function startTargetedGeneration(params: { with_indicators: boolean }) {
    if (!groupConfirm.targetId) return;
    setLastGenerationParams(params);
    try {
      await competenceGenerationApi.create({
        scope: groupConfirm.scope,
        target_id: groupConfirm.targetId,
        params,
      });
      // useGenerationSession polls every 5s while active, but kick a
      // refetch now so the button flips to "AI generation in progress"
      // without waiting for the next tick.
      void refreshActiveSession();
      setDrawerOpen(true);
    } catch (err) {
      // HRP-168: 409 active_session_exists used to silently redirect via
      // window.location.href, which read as "the page just refreshed and
      // Start did nothing." Surface a visible dialog with explicit
      // "Open active" / "Cancel and retry" actions instead.
      if (err instanceof ApiError && err.status === 409) {
        const detail = err.detail;
        if (isActiveSessionConflict(detail) && detail.session) {
          setConflictSession(detail.session);
          return;
        }
      }
      toast.error(
        err instanceof Error ? err.message : t("errorStartGeneration"),
      );
    }
  }

  const generationLocked =
    !!activeSession && activeSession.status !== "applied" && activeSession.status !== "cancelled";
  const generationLockedTargetId = generationLocked
    ? (activeSession?.target_id ?? null)
    : null;

  // HRP-109: every group + sub-group id is a collapsible node. The shared
  // hook treats missing ids as "expanded" by default so the page renders
  // identically to the pre-HRP-109 useState(true) behaviour on first paint.
  // Both `useMemo` and `useTreeExpansion` live above the `if (loading)`
  // early-return so hook order stays stable between renders.
  const allGroupIds = useMemo(() => {
    const ids: string[] = [];
    const walk = (groups: CompetenceGroupTree[]) => {
      for (const g of groups) {
        ids.push(g.id);
        if (g.children?.length) walk(g.children);
      }
    };
    walk(tree);
    return ids;
  }, [tree]);
  const {
    isExpanded: isGroupExpanded,
    toggle: toggleGroupExpanded,
    expandAll: expandAllGroups,
    collapseAll: collapseAllGroups,
    allExpanded: allGroupsExpanded,
    allCollapsed: allGroupsCollapsed,
  } = useTreeExpansion(allGroupIds, "all");

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        {tc("loading")}
      </div>
    );
  }

  const totalCompetences = tree.reduce(
    (acc, g) => acc + g.competences.length,
    0,
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">
            {t("title")}
          </h1>
          <p className="text-sm text-muted-foreground">
            {t("subtitleCounts", {
              groups: tree.length,
              competences: totalCompetences,
            })}
          </p>
        </div>
        {canManage && (
          <div className="flex flex-wrap items-center gap-2">
            <GenerationStatusButton
              totalCompetences={totalCompetences}
              activeSession={activeSession}
              activeSessionLoading={activeSessionLoading}
              onCreated={() => {
                void refreshActiveSession();
                openOwnDrawer();
              }}
              onOpenDrawer={openOwnDrawer}
            />
            <Button data-testid="competences-btn-add-group" size="sm" onClick={() => openCreateGroup()}>
              <Plus className="mr-1 h-4 w-4" />
              {t("addGroup")}
            </Button>
          </div>
        )}
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-base">{t("competenceTree")}</CardTitle>
          {/* HRP-109: bulk expand/collapse for the whole tree. */}
          <TreeExpandControls
            expandAll={expandAllGroups}
            collapseAll={collapseAllGroups}
            allExpanded={allGroupsExpanded}
            allCollapsed={allGroupsCollapsed}
            testIdPrefix="competences-tree"
          />
        </CardHeader>
        <CardContent data-testid="competences-tree">
          {tree.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              {t("emptyGroups")}
            </p>
          ) : (
            <DndContext sensors={dndSensors} onDragEnd={handleDragEnd}>
              <div className="-mx-3">
                {tree.map((group) => (
                  <GroupNode
                    key={group.id}
                    group={group}
                    onEditGroup={openEditGroup}
                    onDeleteGroup={openDeleteGroup}
                    onDeactivateGroup={toggleGroupActive}
                    onAddChild={(parentId) => openCreateGroup(parentId)}
                    onAddCompetence={openCreateCompetence}
                    onBulkAddCompetences={openBulkAddCompetences}
                    onEditCompetence={openEditCompetence}
                    onDeleteCompetence={openDeleteCompetence}
                    onTogglePublishCompetence={togglePublishCompetence}
                    onGenerateGroup={openGenerateGroup}
                    onGenerateIndicators={openGenerateIndicators}
                    generationLocked={generationLocked}
                    generationLockedTargetId={generationLockedTargetId}
                    activeSessionsMap={activeSessionsMap}
                    onOpenActiveSession={openDrawerForSession}
                    isExpanded={isGroupExpanded}
                    onToggleExpand={toggleGroupExpanded}
                  />
                ))}
              </div>
            </DndContext>
          )}
        </CardContent>
      </Card>

      {/* Group dialog */}
      <Dialog open={groupDialogOpen} onOpenChange={setGroupDialogOpen}>
        <DialogContent data-testid="competences-modal-group" className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {groupDialogMode === "create" ? t("addGroup") : t("editGroup")}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>{t("fieldTitle")}</Label>
              <Input
                data-testid="competences-modal-group-input-title"
                value={groupForm.title}
                onChange={(e) =>
                  setGroupForm({ ...groupForm, title: e.target.value })
                }
              />
            </div>
            <div className="space-y-2">
              <Label>{t("fieldDescription")}</Label>
              <Textarea
                data-testid="competences-modal-group-input-description"
                value={groupForm.description}
                onChange={(e) =>
                  setGroupForm({ ...groupForm, description: e.target.value })
                }
                rows={2}
              />
            </div>
            <div className="space-y-2">
              <Label>{t("fieldParentGroup")}</Label>
              <Select
                value={groupForm.parent_id}
                onValueChange={(val) =>
                  setGroupForm({ ...groupForm, parent_id: val })
                }
              >
                <SelectTrigger data-testid="competences-modal-group-select-parent" className="w-full">
                  <SelectValue placeholder={t("noneTopLevel")}>
                    {(() => { if (!groupForm.parent_id) return undefined; const g = flatGroups.find((g) => g.id === groupForm.parent_id); return g ? `${"—".repeat(g.depth)} ${g.title}` : undefined; })()}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">{t("noneTopLevel")}</SelectItem>
                  {flatGroups
                    .filter((g) => g.id !== editingGroupId)
                    .map((g) => (
                      <SelectItem key={g.id} value={g.id}>
                        {"—".repeat(g.depth)} {g.title}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t("fieldSortIndex")}</Label>
              <Input
                type="number"
                value={groupForm.sort_index}
                onChange={(e) =>
                  setGroupForm({ ...groupForm, sort_index: Number(e.target.value) })
                }
              />
            </div>
            {(() => {
              const editingGroup =
                groupDialogMode === "edit" && editingGroupId
                  ? flatGroups.find((g) => g.id === editingGroupId)
                  : undefined;
              // HRP-137: when the group already has client-side usage we hide
              // the activate-by-default checkbox (it cannot be deactivated)
              // and show a read-only "used by client" affordance instead.
              if (editingGroup?.is_used) {
                return (
                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <div
                          className="flex items-center gap-2 rounded-md border bg-muted/30 px-3 py-2 text-sm text-muted-foreground"
                          data-testid="competences-modal-group-used-by-client"
                          tabIndex={-1}
                          aria-label={t("usedByClientAria")}
                        />
                      }
                    >
                      <Link2 className="h-4 w-4 text-primary" />
                      <span>{t("usedByClient")}</span>
                    </TooltipTrigger>
                    <TooltipContent>{t("usedByClientTooltip")}</TooltipContent>
                  </Tooltip>
                );
              }
              return (
                <label
                  className="flex items-center gap-2 text-sm"
                  data-testid="competences-modal-group-checkbox-active-label"
                >
                  <Checkbox
                    checked={groupForm.is_active}
                    onCheckedChange={(v) =>
                      setGroupForm({ ...groupForm, is_active: v === true })
                    }
                    data-testid="competences-modal-group-checkbox-active"
                  />
                  <span>{t("activateByDefault")}</span>
                </label>
              );
            })()}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setGroupDialogOpen(false)} disabled={saving}>
              {tc("cancel")}
            </Button>
            <Button data-testid="competences-modal-group-btn-submit" onClick={saveGroup} disabled={saving}>
              {saving
                ? t("saving")
                : groupDialogMode === "create"
                  ? t("create")
                  : t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Competence dialog (two-step wizard on create, full-form on edit) */}
      <Dialog open={compDialogOpen} onOpenChange={setCompDialogOpen}>
        <DialogContent
          data-testid="competences-modal-competence"
          className="sm:max-w-xl max-h-[90vh] overflow-y-auto"
        >
          <DialogHeader>
            <DialogTitle>
              {compDialogMode === "create" ? (
                <span data-testid="competences-modal-competence-step-label">
                  {t("addCompetenceStep", { step: compStep })}
                </span>
              ) : (
                t("editCompetence")
              )}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            {(compDialogMode === "edit" || compStep === 1) && (
              <>
                <div
                  className="space-y-2"
                  data-testid="competences-modal-competence-step-1"
                >
                  <Label>{t("fieldTitle")}</Label>
                  <Input
                    data-testid="competences-modal-competence-input-title"
                    value={compForm.title}
                    onChange={(e) =>
                      setCompForm({ ...compForm, title: e.target.value })
                    }
                  />
                </div>
                <div className="space-y-2">
                  <Label>{t("fieldDescription")}</Label>
                  <Textarea
                    data-testid="competences-modal-competence-input-description"
                    value={compForm.description}
                    onChange={(e) =>
                      setCompForm({ ...compForm, description: e.target.value })
                    }
                    rows={2}
                  />
                </div>
                <div className="space-y-2">
                  <Label>{t("fieldCompetenceType")}</Label>
                  <Select
                    value={compForm.competence_type_id}
                    onValueChange={(val) =>
                      setCompForm({ ...compForm, competence_type_id: val })
                    }
                  >
                    <SelectTrigger data-testid="competences-modal-competence-select-type" className="w-full">
                      <SelectValue placeholder={t("none")}>
                        {compTypeLabel(compForm.competence_type_id) || t("none")}
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="">{t("none")}</SelectItem>
                      {visibleCompetenceTypes(
                        compTypes,
                        compForm.competence_type_id,
                      ).map((ct) => (
                        <SelectItem key={ct.id} value={ct.id}>
                          {dictionaryItemLabel(tRef, ct)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </>
            )}
            {(compDialogMode === "edit" || compStep === 2) && (
              <div
                className="space-y-2"
                data-testid="competences-modal-competence-step-2"
              >
                <Label>{t("fieldGroup")}</Label>
                <Select
                  value={compForm.group_id}
                  onValueChange={(val) =>
                    setCompForm({ ...compForm, group_id: val })
                  }
                >
                  <SelectTrigger data-testid="competences-modal-competence-select-group" className="w-full">
                    <SelectValue placeholder={t("selectGroup")}>
                      {flatGroups.find((g) => g.id === compForm.group_id)?.title || t("selectGroup")}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {flatGroups.map((g) => (
                      <SelectItem key={g.id} value={g.id}>
                        {"—".repeat(g.depth)} {g.title}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
          {compDialogMode === "edit" && editingCompId && (
            <div className="mt-4 border-t pt-4">
              <IndicatorsEditor
                competenceId={editingCompId}
                disabledReason={
                  generationLocked ? t("activeSessionHint") : null
                }
                onGenerateAi={() => {
                  setCompDialogOpen(false);
                  setGroupConfirm({
                    open: true,
                    scope: "competence_indicators",
                    targetId: editingCompId,
                    targetTitle: compForm.title,
                  });
                }}
                onChanged={invalidateCompetenceTree}
              />
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setCompDialogOpen(false)} disabled={saving}>
              {tc("cancel")}
            </Button>
            {compDialogMode === "create" && compStep === 1 ? (
              <Button
                data-testid="competences-modal-competence-btn-next"
                onClick={() => {
                  if (!compForm.title.trim()) {
                    toast.error(t("errorTitleRequired"));
                    return;
                  }
                  setCompStep(2);
                }}
                disabled={saving}
              >
                {t("next")}
              </Button>
            ) : (
              <>
                {compDialogMode === "create" && (
                  <Button
                    variant="outline"
                    data-testid="competences-modal-competence-btn-back"
                    onClick={() => setCompStep(1)}
                    disabled={saving}
                  >
                    {t("back")}
                  </Button>
                )}
                <Button data-testid="competences-modal-competence-btn-submit" onClick={saveCompetence} disabled={saving}>
                  {saving
                    ? t("saving")
                    : compDialogMode === "create"
                      ? t("create")
                      : t("save")}
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation */}
      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={
          deleteTarget?.type === "competence"
            ? t("deleteCompetence")
            : t("deleteGroup")
        }
        description={t("deleteConfirmDescription", {
          title: deleteTarget?.title ?? "",
        })}
        onConfirm={confirmDelete}
        loading={saving}
      />

      {/* HRP-108 — bulk add competences to a group */}
      <Dialog open={bulkDialogOpen} onOpenChange={setBulkDialogOpen}>
        <DialogContent
          data-testid="competences-modal-bulk"
          className="sm:max-w-2xl max-h-[90vh] overflow-y-auto"
        >
          <DialogHeader>
            <DialogTitle>
              {t("bulkAddTitle", {
                group: bulkTargetGroup?.title ?? t("groupFallback"),
              })}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              {t("bulkAddHint")}
            </p>
            <div className="space-y-2">
              {bulkRows.map((row, idx) => (
                <div
                  key={idx}
                  data-testid={`competences-modal-bulk-row-${idx}`}
                  className="flex gap-2 rounded-md border bg-background p-2"
                >
                  <div className="flex-1 space-y-2">
                    <Input
                      data-testid={`competences-modal-bulk-row-${idx}-title`}
                      placeholder={t("placeholderTitle")}
                      value={row.title}
                      onChange={(e) =>
                        setBulkRows((rows) =>
                          rows.map((r, i) =>
                            i === idx ? { ...r, title: e.target.value } : r,
                          ),
                        )
                      }
                    />
                    <Textarea
                      data-testid={`competences-modal-bulk-row-${idx}-description`}
                      placeholder={t("placeholderDescriptionOptional")}
                      rows={1}
                      value={row.description}
                      onChange={(e) =>
                        setBulkRows((rows) =>
                          rows.map((r, i) =>
                            i === idx
                              ? { ...r, description: e.target.value }
                              : r,
                          ),
                        )
                      }
                    />
                    <Select
                      value={row.competence_type_id}
                      onValueChange={(val) =>
                        setBulkRows((rows) =>
                          rows.map((r, i) =>
                            i === idx
                              ? { ...r, competence_type_id: val }
                              : r,
                          ),
                        )
                      }
                    >
                      <SelectTrigger
                        className="w-full"
                        data-testid={`competences-modal-bulk-row-${idx}-type`}
                      >
                        <SelectValue placeholder={t("placeholderTypeOptional")}>
                          {compTypeLabel(row.competence_type_id) || undefined}
                        </SelectValue>
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="">{t("none")}</SelectItem>
                        {visibleCompetenceTypes(
                          compTypes,
                          row.competence_type_id,
                        ).map((ct) => (
                          <SelectItem key={ct.id} value={ct.id}>
                            {dictionaryItemLabel(tRef, ct)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    data-testid={`competences-modal-bulk-row-${idx}-remove`}
                    onClick={() =>
                      setBulkRows((rows) =>
                        rows.length === 1
                          ? rows
                          : rows.filter((_, i) => i !== idx),
                      )
                    }
                    disabled={saving || bulkRows.length === 1}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
            <Button
              variant="outline"
              size="sm"
              data-testid="competences-modal-bulk-btn-add-row"
              onClick={() =>
                setBulkRows((rows) => [
                  ...rows,
                  { title: "", description: "", competence_type_id: "" },
                ])
              }
              disabled={saving}
            >
              <Plus className="mr-1 h-4 w-4" />
              {t("addRow")}
            </Button>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setBulkDialogOpen(false)}
              disabled={saving}
            >
              {tc("cancel")}
            </Button>
            <Button
              data-testid="competences-modal-bulk-btn-submit"
              onClick={saveBulkCompetences}
              disabled={saving}
            >
              {saving ? t("saving") : t("createAll")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* CR13 — group-scope confirm dialog */}
      <GenerationConfirmDialog
        open={groupConfirm.open}
        onOpenChange={(v) => setGroupConfirm((s) => ({ ...s, open: v }))}
        scope={groupConfirm.scope}
        targetTitle={groupConfirm.targetTitle}
        targetId={groupConfirm.targetId}
        onSubmit={async (params) => {
          await startTargetedGeneration(params);
        }}
      />

      {/* HRP-168: visible conflict dialog instead of silent redirect */}
      <ActiveSessionConflictDialog
        session={conflictSession}
        onClose={() => setConflictSession(null)}
        onRetry={() => {
          setConflictSession(null);
          if (lastGenerationParams) {
            void startTargetedGeneration(lastGenerationParams);
          }
        }}
      />

      {/* CR13 — generation drawer (whole base / group / indicators) */}
      <GenerationDrawer
        open={drawerOpen}
        onOpenChange={(next) => {
          setDrawerOpen(next);
          if (!next) setDrawerSessionId(null);
        }}
        query={drawerSessionId ? { sessionId: drawerSessionId } : "active"}
        targetTitleResolver={(id) =>
          id ? (findGroupTitle(id) ?? findCompetenceTitle(id)) : null
        }
        onApplied={() => {
          void refreshActiveSession();
          refreshActiveSessions();
          reloadAll();
        }}
      />
    </div>
  );
}
