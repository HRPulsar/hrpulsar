import type { LucideIcon } from "lucide-react";
import { BookOpen, Hammer, MessageSquare } from "lucide-react";

export type MaterialFormatOption = {
  value: string;
  label: string;
};

export type MaterialTypeOption = {
  value: string;
  label: string;
  icon: LucideIcon;
};

export const MATERIAL_FORMATS: MaterialFormatOption[] = [
  { value: "documentation", label: "Documentation" },
  { value: "video", label: "Video" },
  { value: "article", label: "Article" },
  { value: "webinar", label: "Webinar" },
  { value: "book", label: "Book" },
  { value: "course", label: "Course" },
  { value: "task", label: "Task" },
  { value: "project", label: "Project" },
  { value: "masterclass", label: "Masterclass" },
  { value: "trainer", label: "Trainer" },
  { value: "conversation", label: "Conversation" },
  { value: "interview", label: "Interview" },
  { value: "mentorship", label: "Mentorship" },
  { value: "training", label: "Training" },
  { value: "exercise", label: "Exercise" },
  { value: "simulator", label: "Simulator" },
  { value: "other", label: "Other" },
];

export const MATERIAL_TYPES: MaterialTypeOption[] = [
  { value: "theoretical", label: "Theoretical", icon: BookOpen },
  { value: "practical", label: "Practical", icon: Hammer },
  { value: "feedback", label: "Feedback", icon: MessageSquare },
];

export const DEFAULT_MATERIAL_TYPE = "theoretical";

export function materialFormatLabel(value: string | null | undefined): string | null {
  if (!value) return null;
  return MATERIAL_FORMATS.find((f) => f.value === value)?.label ?? value;
}

export function materialTypeOption(
  value: string | null | undefined,
): MaterialTypeOption | null {
  if (!value) return null;
  return MATERIAL_TYPES.find((t) => t.value === value) ?? null;
}
