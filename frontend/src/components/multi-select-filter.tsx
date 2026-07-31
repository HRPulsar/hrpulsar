"use client";

import { useEffect, useMemo, useRef } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

export interface MultiSelectOption {
  value: string;
  label: string;
}

interface MultiSelectFilterProps {
  options: MultiSelectOption[];
  value: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
  className?: string;
  disabled?: boolean;
  "data-testid"?: string;
}

export function MultiSelectFilter({
  options,
  value,
  onChange,
  placeholder,
  className,
  disabled,
  "data-testid": testId,
}: MultiSelectFilterProps) {
  const t = useTranslations("common");
  const selected = useMemo(() => new Set(value), [value]);

  const labelText = useMemo(() => {
    if (value.length === 0) return placeholder;
    if (value.length === 1) {
      const opt = options.find((o) => o.value === value[0]);
      return opt?.label ?? placeholder;
    }
    return `${placeholder} (${value.length})`;
  }, [options, placeholder, value]);

  // With `closeOnClick={false}` the user can fire several toggles before
  // React commits any of the `onChange` calls. Reading `value` directly
  // inside `toggle` captures the stale snapshot at the last render and
  // every successive click overwrites the previous one (the URL ends up
  // with just the most recent selection). A ref tracks the latest value
  // synchronously so each toggle composes onto whatever was just sent.
  const valueRef = useRef(value);
  useEffect(() => {
    valueRef.current = value;
  }, [value]);

  function toggle(val: string, checked: boolean) {
    const current = valueRef.current;
    if (checked) {
      if (current.includes(val)) return;
      const next = [...current, val];
      valueRef.current = next;
      onChange(next);
    } else {
      const next = current.filter((v) => v !== val);
      valueRef.current = next;
      onChange(next);
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        disabled={disabled}
        data-testid={testId}
        render={
          <Button
            variant="outline"
            size="sm"
            className={cn(
              "justify-between font-normal",
              value.length === 0 && "text-muted-foreground",
              className,
            )}
          />
        }
      >
        <span className="truncate">{labelText}</span>
        <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        className="max-h-72 min-w-[--anchor-width] overflow-y-auto"
      >
        {options.length === 0 ? (
          <div className="px-2 py-2 text-xs text-muted-foreground">
            {t("noOptions")}
          </div>
        ) : (
          options.map((opt) => (
            <DropdownMenuCheckboxItem
              key={opt.value}
              checked={selected.has(opt.value)}
              onCheckedChange={(checked) => toggle(opt.value, Boolean(checked))}
              // Base UI closes the menu on each item click by default; for a
              // multi-select that means the operator (and the e2e walk) loses
              // the dropdown after the first selection and the second click
              // lands on an unrelated element. Keep the menu open so further
              // selections register correctly.
              closeOnClick={false}
              data-testid={
                testId ? `${testId}-option-${opt.value}` : undefined
              }
            >
              {opt.label}
            </DropdownMenuCheckboxItem>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
