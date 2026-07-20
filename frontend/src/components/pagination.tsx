"use client";

import { Button } from "@/components/ui/button";
import { ChevronLeft, ChevronRight } from "lucide-react";

interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
}

export function Pagination({ page, pageSize, total, onPageChange }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  if (totalPages <= 1) return null;

  const pages: (number | "...")[] = [];
  for (let i = 1; i <= totalPages; i++) {
    if (i === 1 || i === totalPages || (i >= page - 1 && i <= page + 1)) {
      pages.push(i);
    } else if (pages[pages.length - 1] !== "...") {
      pages.push("...");
    }
  }

  return (
    <div className="flex items-center justify-between" data-testid="pagination">
      <p className="text-sm text-muted-foreground">
        {Math.min((page - 1) * pageSize + 1, total)}–{Math.min(page * pageSize, total)} of {total}
      </p>
      <div className="flex items-center gap-1">
        <Button
          variant="outline"
          size="icon-xs"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
          data-testid="pagination-btn-prev"
        >
          <ChevronLeft className="h-3 w-3" />
        </Button>
        {pages.map((p, i) =>
          p === "..." ? (
            <span key={`e${i}`} className="px-1 text-xs text-muted-foreground">...</span>
          ) : (
            <Button
              key={p}
              variant={p === page ? "default" : "outline"}
              size="xs"
              onClick={() => onPageChange(p)}
              data-testid={`pagination-btn-page-${p}`}
            >
              {p}
            </Button>
          ),
        )}
        <Button
          variant="outline"
          size="icon-xs"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
          data-testid="pagination-btn-next"
        >
          <ChevronRight className="h-3 w-3" />
        </Button>
      </div>
    </div>
  );
}
