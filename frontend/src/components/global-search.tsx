"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { usePermissions } from "@/hooks/use-permissions";
import { api } from "@/lib/api";
import type { AssessmentList, CandidateList, EmployeeList, VacancyList } from "@/lib/types";
import {
  assessmentStatusTitle,
  assessmentTypeTitle,
  gradeTitleLabel,
} from "@/lib/reference-labels";
import { vacancyStatusBadgeLabel } from "@/lib/vacancy-status";
import { Input } from "@/components/ui/input";
import { Search } from "lucide-react";

// Rows asked for per type; the dropdown shows each type's best few.
const PER_TYPE = 5;

interface SearchResult {
  type: "employee" | "assessment" | "vacancy" | "candidate";
  id: string;
  title: string;
  subtitle: string;
  href: string;
}

export function GlobalSearch() {
  const t = useTranslations("common");
  const tRef = useTranslations("reference");
  const tRec = useTranslations("recruitment");
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // HRP-829 REDO: every employee result opens a card, and with the section
  // closed no card opens - so no employee results at all. At view / manage
  // every row the list answers is a card the caller may open.
  const searchEmployees = usePermissions().canViewSection("employees");
  // A slow answer to an earlier query must not overwrite a newer one.
  const latestRef = useRef(0);

  const search = useCallback(async (raw: string) => {
    const request = ++latestRef.current;
    // Every list searches the same trimmed text; blank is no query at all.
    const q = raw.trim();
    if (q.length < 2) {
      setResults([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      // HRP-1067: the server searches the whole list - filtering one loaded
      // page missed everyone past it. `tenant_wide` lets a manager find
      // colleagues outside their subtree, as on the Employees page.
      const term = `q=${encodeURIComponent(q)}&limit=${PER_TYPE}`;
      const [empData, asmtData, vacData, candData] = await Promise.all([
        searchEmployees
          ? api.get<EmployeeList>(`/employees?${term}&tenant_wide=true`)
          : Promise.resolve<Pick<EmployeeList, "items">>({ items: [] }),
        api.get<AssessmentList>(`/assessments?${term}`).catch(() => ({ items: [] })),
        api.get<VacancyList>(`/recruitment/vacancies?${term}`).catch(() => ({ items: [] })),
        api.get<CandidateList>(`/recruitment/candidates?${term}`).catch(() => ({ items: [] })),
      ]);
      if (request !== latestRef.current) return;

      const empResults: SearchResult[] = empData.items.map((e) => ({
        type: "employee",
        id: e.id,
        title: e.user_name || e.user_email || t("employee"),
        subtitle: e.position_title || "",
        href: `/employees/${e.id}`,
      }));

      const asmtResults: SearchResult[] = asmtData.items.map((a) => ({
        type: "assessment",
        id: a.id,
        title: a.title || t("untitled"),
        subtitle: `${assessmentTypeTitle(tRef, a)} — ${assessmentStatusTitle(tRef, a)}`,
        href: `/assessments/${a.id}`,
      }));

      const vacResults: SearchResult[] = (vacData.items || []).map((v) => ({
        type: "vacancy" as const,
        id: v.id,
        title: v.title,
        subtitle: `${v.specialization_title || ""} ${gradeTitleLabel(tRef, v.grade_title)} — ${vacancyStatusBadgeLabel(tRec, v.status)}`.trim(),
        href: `/recruitment/requisitions/${v.id}`,
      }));

      const candResults: SearchResult[] = (candData.items || []).map((c) => {
        const name = (
          c.full_name ||
          (c.person ? `${c.person.first_name} ${c.person.last_name}` : "")
        ).trim();
        return {
          type: "candidate" as const,
          id: c.id,
          title: name || t("unnamed"),
          subtitle: c.email || c.person?.email || c.source || "",
          href: `/recruitment/candidates/${c.id}`,
        };
      });

      setResults([...empResults, ...asmtResults, ...vacResults, ...candResults]);
      setSelectedIdx(0);
    } catch {
      if (request === latestRef.current) setResults([]);
    } finally {
      if (request === latestRef.current) setLoading(false);
    }
  }, [t, tRef, tRec, searchEmployees]);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => search(query), 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, search]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIdx((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && results[selectedIdx]) {
      e.preventDefault();
      navigate(results[selectedIdx].href);
    } else if (e.key === "Escape") {
      setOpen(false);
      setQuery("");
    }
  }

  function navigate(href: string) {
    setOpen(false);
    setQuery("");
    setResults([]);
    router.push(href);
  }

  // Keyboard shortcut: Cmd/Ctrl+K
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen(true);
        setTimeout(() => inputRef.current?.focus(), 0);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  const typeLabels: Record<string, string> = {
    employee: t("employee"),
    assessment: t("assessment"),
    vacancy: t("vacancy"),
    candidate: t("candidate"),
  };

  return (
    <div className="relative w-full max-w-[420px] flex-1">
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          ref={inputRef}
          placeholder={t("searchPlaceholder")}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            if (!open) setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={handleKeyDown}
          className="h-8 w-full pr-12 pl-8 text-[12.5px]"
          data-testid="header-search"
        />
        <kbd className="pointer-events-none absolute top-1/2 right-2 -translate-y-1/2 rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
          ⌘K
        </kbd>
      </div>

      {open && query.trim().length >= 2 && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 z-40" onClick={() => { setOpen(false); setQuery(""); }} />

          {/* Results dropdown */}
          <div className="absolute left-0 top-full z-50 mt-1 w-80 rounded-lg border bg-background shadow-lg">
            {loading ? (
              <div className="p-3 text-center text-sm text-muted-foreground">{t("searching")}</div>
            ) : results.length === 0 ? (
              <div className="p-3 text-center text-sm text-muted-foreground">{t("noResults")}</div>
            ) : (
              <div className="max-h-72 overflow-y-auto p-1">
                {results.map((r, i) => (
                  <button
                    key={`${r.type}-${r.id}`}
                    className={`flex w-full items-start gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors ${
                      i === selectedIdx ? "bg-muted" : "hover:bg-muted/50"
                    }`}
                    onClick={() => navigate(r.href)}
                    onMouseEnter={() => setSelectedIdx(i)}
                  >
                    <span className="mt-0.5 rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                      {typeLabels[r.type]}
                    </span>
                    <div className="flex-1">
                      <p className="font-medium">{r.title}</p>
                      <p className="text-xs text-muted-foreground">{r.subtitle}</p>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
