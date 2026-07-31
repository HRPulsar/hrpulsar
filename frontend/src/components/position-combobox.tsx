"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import * as Popover from "@radix-ui/react-popover";
import { Command } from "cmdk";
import { api } from "@/lib/api";
import type { Position, PositionList } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Check, ChevronsUpDown, Plus, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface PositionComboboxProps {
  value: string | null;
  onValueChange: (
    positionId: string | null,
    positionTitle: string | null,
  ) => void;
  placeholder?: string;
  disabled?: boolean;
  "data-testid"?: string;
}

export function PositionCombobox({
  value,
  onValueChange,
  placeholder,
  disabled,
  "data-testid": testId,
}: PositionComboboxProps) {
  const t = useTranslations("company");
  const tc = useTranslations("common");
  const resolvedPlaceholder = placeholder ?? t("selectPositionPlaceholder");
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedTitle, setSelectedTitle] = useState<string | null>(null);

  // Quick-create
  const [showCreate, setShowCreate] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [creating, setCreating] = useState(false);

  const loadPositions = useCallback(async (query: string) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        is_active: "true",
        limit: "50",
      });
      if (query) params.set("search", query);
      const data = await api.get<PositionList>(`/positions?${params}`);
      setPositions(data.items.filter((p) => p.source !== "ai_draft"));
    } catch {
      setPositions([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // Load on open
  useEffect(() => {
    if (open) {
      loadPositions("");
      setSearch("");
      setShowCreate(false);
      setNewTitle("");
    }
  }, [open, loadPositions]);

  // Debounced search
  useEffect(() => {
    if (!open) return;
    const timeout = setTimeout(() => loadPositions(search), 200);
    return () => clearTimeout(timeout);
  }, [search, open, loadPositions]);

  // Resolve initial title from value
  useEffect(() => {
    if (value && !selectedTitle) {
      api
        .get<Position>(`/positions/${value}`)
        .then((p) => setSelectedTitle(p.title))
        .catch(() => setSelectedTitle(null));
    } else if (!value) {
      setSelectedTitle(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  function handleSelect(pos: Position) {
    onValueChange(pos.id, pos.title);
    setSelectedTitle(pos.title);
    setOpen(false);
  }

  function handleClear(e: React.MouseEvent) {
    e.stopPropagation();
    onValueChange(null, null);
    setSelectedTitle(null);
  }

  async function handleQuickCreate() {
    if (!newTitle.trim()) return;
    setCreating(true);
    try {
      const pos = await api.post<Position>("/positions", {
        title: newTitle.trim(),
      });
      onValueChange(pos.id, pos.title);
      setSelectedTitle(pos.title);
      setOpen(false);
    } catch {
      // api layer shows toast
    } finally {
      setCreating(false);
    }
  }

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild disabled={disabled}>
        <button
          type="button"
          role="combobox"
          aria-expanded={open}
          aria-controls="position-combobox-list"
          aria-label={t("selectPosition")}
          data-testid={testId}
          className={cn(
            "flex h-8 w-full items-center justify-between rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-input/30 dark:hover:bg-input/50",
            !selectedTitle && "text-muted-foreground",
          )}
        >
          <span className="flex-1 truncate text-left">
            {selectedTitle || resolvedPlaceholder}
          </span>
          <span className="flex items-center gap-1">
            {selectedTitle && (
              <span
                role="button"
                tabIndex={-1}
                onClick={handleClear}
                className="rounded-sm p-0.5 hover:bg-muted"
                aria-label={t("clearPosition")}
              >
                <X className="h-3 w-3" />
              </span>
            )}
            <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
          </span>
        </button>
      </Popover.Trigger>

      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={4}
          className="z-50 w-[--radix-popover-trigger-width] rounded-lg border bg-popover shadow-md outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95"
          onOpenAutoFocus={(e) => e.preventDefault()}
        >
          <Command shouldFilter={false} className="flex flex-col">
            <div className="flex items-center border-b px-3">
              <Command.Input
                value={search}
                onValueChange={setSearch}
                placeholder={t("searchPositionsPlaceholder")}
                className="flex h-9 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
              />
            </div>
            <Command.List id="position-combobox-list" className="max-h-52 overflow-y-auto p-1">
              {loading && (
                <Command.Loading>
                  <div className="px-2 py-3 text-center text-xs text-muted-foreground">
                    {tc("loading")}
                  </div>
                </Command.Loading>
              )}
              <Command.Empty className="px-2 py-3 text-center text-xs text-muted-foreground">
                {t("noPositionsFound")}
              </Command.Empty>
              {positions.map((pos) => (
                <Command.Item
                  key={pos.id}
                  value={pos.id}
                  onSelect={() => handleSelect(pos)}
                  className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm aria-selected:bg-accent aria-selected:text-accent-foreground"
                >
                  <Check
                    className={cn(
                      "h-4 w-4 shrink-0",
                      value === pos.id ? "opacity-100" : "opacity-0",
                    )}
                  />
                  <span className="flex-1 truncate">{pos.title}</span>
                  {pos.grade_title && (
                    <span className="text-xs text-muted-foreground">
                      {pos.grade_title}
                    </span>
                  )}
                </Command.Item>
              ))}
            </Command.List>

            {/* Quick create */}
            <div className="border-t p-2">
              {showCreate ? (
                <div className="flex gap-1">
                  <Input
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    placeholder={t("positionTitlePlaceholder")}
                    className="h-7 flex-1 text-sm"
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        handleQuickCreate();
                      }
                      if (e.key === "Escape") setShowCreate(false);
                    }}
                    autoFocus
                  />
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 px-2"
                    onClick={handleQuickCreate}
                    disabled={creating || !newTitle.trim()}
                  >
                    {creating ? "..." : t("add")}
                  </Button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    setNewTitle(search);
                    setShowCreate(true);
                  }}
                  className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                >
                  <Plus className="h-3.5 w-3.5" />
                  {t("createNewPosition")}
                </button>
              )}
            </div>
          </Command>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
