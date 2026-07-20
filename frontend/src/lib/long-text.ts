// HRP-319: shared "Show more / Show less" trimming used by the vacancy Overview
// block. View-mode collapses every long text field at the same character limit
// so the whole section keeps its scan-able rhythm regardless of which field is
// long.
export const LONG_TEXT_THRESHOLD = 300;

export interface TrimmedLongText {
  visible: string;
  isLong: boolean;
}

export function trimLongText(
  text: string,
  expanded: boolean,
  threshold: number = LONG_TEXT_THRESHOLD,
): TrimmedLongText {
  const isLong = text.length > threshold;
  if (!isLong || expanded) {
    return { visible: text, isLong };
  }
  return { visible: `${text.slice(0, threshold)}…`, isLong };
}
