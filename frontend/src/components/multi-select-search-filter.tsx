"use client";

import { useMemo, useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import { Check, ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface MultiSelectSearchOption {
  value: string;
  label: string;
}

interface MultiSelectSearchFilterProps {
  options: MultiSelectSearchOption[];
  value: string[];
  onChange: (next: string[]) => void;
  /** Facet name, shown alone when nothing is picked. */
  placeholder: string;
  searchPlaceholder: string;
  className?: string;
  disabled?: boolean;
  "data-testid"?: string;
}

/**
 * Multi-select with an in-list search box.
 *
 * `MultiSelectFilter` covers the no-search case on a Base UI dropdown, whose
 * typeahead fights a text input; this variant is a Radix popover so the
 * search field owns the keyboard. Filtering is client-side — every caller so
 * far holds the full option list already.
 */
export function MultiSelectSearchFilter({
  options,
  value,
  onChange,
  placeholder,
  searchPlaceholder,
  className,
  disabled,
  "data-testid": testId,
}: MultiSelectSearchFilterProps) {
  const t = useTranslations("common");
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");

  const selected = useMemo(() => new Set(value), [value]);

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return options;
    return options.filter((o) => o.label.toLowerCase().includes(needle));
  }, [options, search]);

  const label = useMemo(() => {
    if (value.length === 0) return placeholder;
    if (value.length === 1) {
      return options.find((o) => o.value === value[0])?.label ?? placeholder;
    }
    return `${placeholder} (${value.length})`;
  }, [options, placeholder, value]);

  function toggle(optionValue: string) {
    onChange(
      selected.has(optionValue)
        ? value.filter((v) => v !== optionValue)
        : [...value, optionValue],
    );
  }

  return (
    <Popover.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setSearch("");
      }}
    >
      <Popover.Trigger asChild disabled={disabled}>
        <Button
          variant="outline"
          size="sm"
          className={cn(
            "justify-between font-normal",
            value.length === 0 && "text-muted-foreground",
            className,
          )}
          data-testid={testId}
        >
          <span className="truncate">{label}</span>
          <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </Popover.Trigger>

      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={4}
          className="z-50 w-(--radix-popover-trigger-width) min-w-56 rounded-lg border bg-popover shadow-md outline-none"
        >
          <div className="border-b px-3">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={searchPlaceholder}
              className="flex h-9 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
              data-testid={testId ? `${testId}-search` : undefined}
            />
          </div>
          <div className="max-h-60 overflow-y-auto p-1">
            {visible.length === 0 ? (
              <div className="px-2 py-3 text-center text-xs text-muted-foreground">
                {t("noOptions")}
              </div>
            ) : (
              visible.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => toggle(option.value)}
                  className="flex w-full cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent hover:text-accent-foreground"
                  data-testid={
                    testId ? `${testId}-option-${option.value}` : undefined
                  }
                >
                  <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                    {selected.has(option.value) && <Check className="h-4 w-4" />}
                  </span>
                  <span className="truncate">{option.label}</span>
                </button>
              ))
            )}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
