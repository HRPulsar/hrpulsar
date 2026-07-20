"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// HRP-360: mirrors backend HiringManagerOption (schemas.py).
export interface HiringManagerOption {
  id: string;
  full_name: string;
  email: string;
}

interface HiringManagerSelectProps {
  value: string | null;
  onChange: (next: string | null) => void;
  disabled?: boolean;
  id?: string;
  testId: string;
  /** Label shown when the stored value is absent from the options list
   * (e.g. the assigned manager has since lost the admin role). */
  fallbackLabel?: string | null;
}

export function HiringManagerSelect({
  value,
  onChange,
  disabled,
  id,
  testId,
  fallbackLabel,
}: HiringManagerSelectProps) {
  const [options, setOptions] = useState<HiringManagerOption[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.get<HiringManagerOption[]>(
          "/recruitment/hiring-managers",
        );
        if (cancelled) return;
        setOptions(Array.isArray(data) ? data : []);
      } catch {
        // ignore — the field falls back to the preselected value
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedLabel = value
    ? (options.find((m) => m.id === value)?.full_name ??
      fallbackLabel ??
      "Select hiring manager")
    : "Select hiring manager";

  return (
    <Select
      value={value ?? ""}
      onValueChange={(val: string) => onChange(val || null)}
      disabled={disabled}
    >
      <SelectTrigger id={id} data-testid={testId}>
        <SelectValue placeholder="Select hiring manager">
          {selectedLabel}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {options.length === 0 ? (
          <div className="px-2 py-1 text-xs text-muted-foreground">
            No eligible users
          </div>
        ) : (
          options.map((m) => (
            <SelectItem key={m.id} value={m.id}>
              {m.full_name}
            </SelectItem>
          ))
        )}
      </SelectContent>
    </Select>
  );
}
