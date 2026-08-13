/**
 * HRP-58 review fix: drain a paginated list endpoint instead of taking
 * the first page and hoping it was everything.
 *
 * The division page derives counters from the employee array it holds —
 * specialization plate counts, "X of Y" in the header, the headcount in
 * the info card, the dropdown option sets. A single `limit=500` request
 * silently truncates on any tenant bigger than that, and the numbers are
 * then wrong in a way nobody can see: the plates undercount, and turning
 * "Include sub-divisions" off filters an already-truncated array, so a
 * division that demonstrably has people can render as empty.
 *
 * `total` from the response is the authority on when to stop.
 */

export interface PagedResponse<T> {
  items: T[];
  total: number;
}

export interface DrainedPages<T> extends PagedResponse<T> {
  /** False when the walk stopped before reaching `total` (see MAX_PAGES). */
  complete: boolean;
}

/** The API caps `limit` at 500 (`le=500` on the employees endpoint). */
export const MAX_PAGE_SIZE = 500;

/**
 * Safety valve against a pathological `total` (a corrupt count would
 * otherwise spin the browser). 200 pages x 500 = 100k rows — far past
 * any realistic single division, so hitting it means something is wrong
 * rather than something is big.
 */
const MAX_PAGES = 200;

export async function fetchAllPages<T>(
  fetchPage: (skip: number, limit: number) => Promise<PagedResponse<T>>,
  pageSize: number = MAX_PAGE_SIZE,
): Promise<DrainedPages<T>> {
  const items: T[] = [];
  let total = 0;
  let skip = 0;

  for (let page = 0; page < MAX_PAGES; page += 1) {
    const response = await fetchPage(skip, pageSize);
    total = response.total ?? 0;
    items.push(...response.items);
    // An empty page means the server has nothing more to give, whatever
    // `total` claims — stop rather than loop forever on a stale count.
    if (response.items.length === 0) break;
    if (items.length >= total) break;
    skip += response.items.length;
  }

  return { items, total, complete: items.length >= total };
}
