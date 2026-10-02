import { api } from "../api";
import type { SectionCode } from "@/lib/sections";

export type MatrixLevel = "none" | "view" | "manage";

export interface SectionAccessSection {
  code: SectionCode;
  hidden: boolean;
  admin_locked: boolean;
  never_hidden: boolean;
  defaults: Record<string, MatrixLevel>;
  levels: Record<string, MatrixLevel>;
}

export interface SectionAccess {
  roles: string[];
  sections: SectionAccessSection[];
}

export interface SectionAccessUpdate {
  sections: { code: SectionCode; hidden: boolean; levels: Record<string, MatrixLevel> }[];
}

const BASE = "/settings/section-access";

export const sectionAccessApi = {
  get: () => api.get<SectionAccess>(BASE),
  update: (body: SectionAccessUpdate) => api.put<SectionAccess>(BASE, body),
};
