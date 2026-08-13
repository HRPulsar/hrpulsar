// HRP-58 review fix: the division page must not compute counters from a
// silently truncated array. `fetchAllPages` drains the endpoint using
// `total` from the response as the stop condition.

import { describe, expect, it, vi } from "vitest";

import { fetchAllPages, MAX_PAGE_SIZE } from "@/lib/api/paginate";

/** A fake endpoint over a fixed row set, honouring skip/limit. */
function pagedSource(rowCount: number, totalOverride?: number) {
  const rows = Array.from({ length: rowCount }, (_, i) => ({ id: `e${i}` }));
  const calls: { skip: number; limit: number }[] = [];
  const fetchPage = vi.fn(async (skip: number, limit: number) => {
    calls.push({ skip, limit });
    return {
      items: rows.slice(skip, skip + limit),
      total: totalOverride ?? rows.length,
    };
  });
  return { fetchPage, calls };
}

describe("fetchAllPages (HRP-58)", () => {
  it("returns everything in one request when it fits on a page", async () => {
    const { fetchPage } = pagedSource(120);
    const result = await fetchAllPages(fetchPage);
    expect(result.items).toHaveLength(120);
    expect(result.complete).toBe(true);
    expect(fetchPage).toHaveBeenCalledTimes(1);
  });

  it("stops after one request when the page exactly equals total", async () => {
    const { fetchPage } = pagedSource(MAX_PAGE_SIZE);
    const result = await fetchAllPages(fetchPage);
    expect(result.items).toHaveLength(MAX_PAGE_SIZE);
    expect(fetchPage).toHaveBeenCalledTimes(1);
  });

  it("drains a tenant larger than one page", async () => {
    // The regression: 1200 employees behind a 500 cap used to yield 500,
    // and every counter on the page was computed from that.
    const { fetchPage, calls } = pagedSource(1200);
    const result = await fetchAllPages(fetchPage);
    expect(result.items).toHaveLength(1200);
    expect(result.total).toBe(1200);
    expect(result.complete).toBe(true);
    expect(calls).toEqual([
      { skip: 0, limit: MAX_PAGE_SIZE },
      { skip: 500, limit: MAX_PAGE_SIZE },
      { skip: 1000, limit: MAX_PAGE_SIZE },
    ]);
    // No duplicates and no gaps.
    expect(new Set(result.items.map((r) => r.id)).size).toBe(1200);
  });

  it("honours a custom page size", async () => {
    const { fetchPage } = pagedSource(25);
    const result = await fetchAllPages(fetchPage, 10);
    expect(result.items).toHaveLength(25);
    expect(fetchPage).toHaveBeenCalledTimes(3);
  });

  it("stops on an empty page even when total over-reports", async () => {
    // A stale count must not spin the loop forever.
    const { fetchPage } = pagedSource(30, 900);
    const result = await fetchAllPages(fetchPage, 10);
    expect(result.items).toHaveLength(30);
    expect(result.complete).toBe(false);
  });

  it("handles an empty division", async () => {
    const { fetchPage } = pagedSource(0);
    const result = await fetchAllPages(fetchPage);
    expect(result.items).toEqual([]);
    expect(result.total).toBe(0);
    expect(result.complete).toBe(true);
    expect(fetchPage).toHaveBeenCalledTimes(1);
  });

  it("gives up rather than hanging on a pathological total", async () => {
    const fetchPage = vi.fn(async (skip: number, limit: number) => ({
      items: Array.from({ length: limit }, (_, i) => ({ id: `e${skip + i}` })),
      total: Number.MAX_SAFE_INTEGER,
    }));
    const result = await fetchAllPages(fetchPage, 10);
    expect(result.complete).toBe(false);
    expect(fetchPage.mock.calls.length).toBeLessThanOrEqual(200);
  });
});
