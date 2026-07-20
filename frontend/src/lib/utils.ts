import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Client-side unique id for optimistic/draft entities. crypto.randomUUID
// is only defined in secure contexts — a plain-HTTP self-hosted install
// must fall back instead of throwing on the first click.
export function newClientId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `key-${Math.random().toString(36).slice(2)}-${Date.now()}`;
}

export function flattenTree<T extends { children?: T[] }>(
  nodes: T[],
  depth = 0,
): (T & { depth: number })[] {
  const result: (T & { depth: number })[] = [];
  for (const node of nodes) {
    const { children } = node;
    result.push({ ...node, depth });
    if (children && children.length > 0) {
      result.push(...flattenTree(children, depth + 1));
    }
  }
  return result;
}
