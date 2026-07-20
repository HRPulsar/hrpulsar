"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import type {
  ApplyResult,
  CompetenceGenerationSession,
  GeneratedCompetence,
  GeneratedGroup,
  GeneratedIndicator,
  SuggestionEdit,
} from "@/lib/api/competence-generation";
import { specializationAiApi } from "@/lib/api/specialization-ai";

interface Props {
  session: CompetenceGenerationSession;
  onApplied: (result: ApplyResult) => void;
  onCancel: () => void;
}

type Selection = Record<string, boolean>;
type Edits = Record<string, SuggestionEdit>;

// HRP-71 phase 3: every node walks one of three states. Pending is the
// implicit default (id absent from selection) — we render it with an orange
// tint so reviewers can see at a glance how much is still un-reviewed.
type NodeState = "accepted" | "rejected" | "pending";

function stateOf(id: string, selection: Selection): NodeState {
  if (!(id in selection)) return "pending";
  return selection[id] ? "accepted" : "rejected";
}

function collectTempIds(payload: CompetenceGenerationSession["payload"]): string[] {
  const ids: string[] = [];
  function visitGroup(g: GeneratedGroup) {
    if (g.temp_id) ids.push(g.temp_id);
    for (const c of g.competences ?? []) {
      if (c.temp_id) ids.push(c.temp_id);
      for (const ind of c.indicators ?? []) {
        if (ind.temp_id) ids.push(ind.temp_id);
      }
    }
    for (const sub of g.children ?? []) visitGroup(sub);
  }
  for (const g of payload?.groups ?? []) visitGroup(g);
  for (const ind of payload?.indicators ?? []) {
    if (ind.temp_id) ids.push(ind.temp_id);
  }
  return ids;
}

function collectAncestorChain(
  payload: CompetenceGenerationSession["payload"],
  target: string,
): string[] {
  const parents: string[] = [];
  function descend(g: GeneratedGroup, chain: string[]): boolean {
    const here = g.temp_id ? [...chain, g.temp_id] : chain;
    if (g.temp_id === target) {
      parents.push(...chain);
      return true;
    }
    for (const c of g.competences ?? []) {
      const compChain = c.temp_id ? [...here, c.temp_id] : here;
      if (c.temp_id === target) {
        parents.push(...here);
        return true;
      }
      for (const ind of c.indicators ?? []) {
        if (ind.temp_id === target) {
          parents.push(...compChain);
          return true;
        }
      }
    }
    for (const sub of g.children ?? []) {
      if (descend(sub, here)) return true;
    }
    return false;
  }
  for (const g of payload?.groups ?? []) {
    if (descend(g, [])) return parents;
  }
  return parents;
}

export function AIReviewModal({ session, onApplied, onCancel }: Props) {
  const [selection, setSelection] = useState<Selection>(() => {
    const raw = (session.selection_state ?? {}) as Record<string, unknown>;
    const next: Selection = {};
    for (const [k, v] of Object.entries(raw)) {
      if (k === "_edits") continue;
      if (typeof v === "boolean") next[k] = v;
    }
    return next;
  });
  const [edits, setEdits] = useState<Edits>(() => {
    const raw = (session.selection_state ?? {}) as Record<string, unknown>;
    const stored = raw["_edits"];
    if (!stored || typeof stored !== "object") return {};
    const out: Edits = {};
    for (const [tid, payload] of Object.entries(stored as Record<string, unknown>)) {
      if (
        payload &&
        typeof payload === "object" &&
        "title" in (payload as object) &&
        typeof (payload as { title: unknown }).title === "string"
      ) {
        out[tid] = { title: (payload as { title: string }).title };
      }
    }
    return out;
  });
  const [editingId, setEditingId] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  // Snapshot the initial edits so Cancel/Close can detect unsaved renames
  // (selection clicks are easy to redo, but typed-out titles aren't).
  const initialEditsRef = useRef<Edits>(edits);
  const editsDirty = useMemo(() => {
    const a = initialEditsRef.current;
    const aKeys = Object.keys(a);
    const bKeys = Object.keys(edits);
    if (aKeys.length !== bKeys.length) return true;
    for (const k of bKeys) {
      if (a[k]?.title !== edits[k]?.title) return true;
    }
    return false;
  }, [edits]);

  const requestClose = useCallback(() => {
    if (
      editsDirty &&
      !window.confirm(
        "You have unsaved title edits. Close without applying?",
      )
    ) {
      return;
    }
    onCancel();
  }, [editsDirty, onCancel]);

  const groups = (session.payload?.groups ?? []) as GeneratedGroup[];
  const allTempIds = useMemo(
    () => collectTempIds(session.payload),
    [session.payload],
  );

  const pendingCount = useMemo(
    () => allTempIds.filter((id) => stateOf(id, selection) === "pending").length,
    [allTempIds, selection],
  );

  function setNode(id: string, value: boolean) {
    setSelection((prev) => {
      const next = { ...prev, [id]: value };
      if (value) {
        for (const ancestor of collectAncestorChain(session.payload, id)) {
          next[ancestor] = true;
        }
      }
      return next;
    });
  }

  function setSubtree(node: GeneratedGroup, value: boolean) {
    setSelection((prev) => {
      const next = { ...prev };
      const visit = (g: GeneratedGroup) => {
        if (g.temp_id) next[g.temp_id] = value;
        for (const c of g.competences ?? []) {
          if (c.temp_id) next[c.temp_id] = value;
          for (const ind of c.indicators ?? []) {
            if (ind.temp_id) next[ind.temp_id] = value;
          }
        }
        for (const sub of g.children ?? []) visit(sub);
      };
      visit(node);
      return next;
    });
  }

  function setCompetenceSubtree(comp: GeneratedCompetence, value: boolean) {
    setSelection((prev) => {
      const next = { ...prev };
      if (comp.temp_id) next[comp.temp_id] = value;
      for (const ind of comp.indicators ?? []) {
        if (ind.temp_id) next[ind.temp_id] = value;
      }
      return next;
    });
  }

  function applyToAll(value: boolean) {
    setSelection(() => {
      const next: Selection = {};
      for (const id of allTempIds) next[id] = value;
      return next;
    });
  }

  function saveEdit(id: string, title: string) {
    const trimmed = title.trim();
    setEdits((prev) => {
      const next = { ...prev };
      if (trimmed) next[id] = { title: trimmed };
      else delete next[id];
      return next;
    });
    setEditingId(null);
  }

  async function handleApply() {
    if (applying) return;
    setApplying(true);
    try {
      await specializationAiApi.replaceSelection(session.id, selection, edits);
      const idempotency_key = `apply-${session.id}-${Date.now()}`;
      const result = await specializationAiApi.apply(session.id, {
        publish: true,
        idempotency_key,
      });
      // HRP-105: caller decides the success vs warning copy — it knows
      // whether 0-new is normal (matrix is full) or surprising (position
      // page expected fresh competences). Just hand over the raw counts.
      onApplied(result);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Apply failed");
    } finally {
      setApplying(false);
    }
  }

  return (
    <div
      data-testid="ai-review-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-md bg-background shadow-lg">
        <header className="flex items-center justify-between border-b px-6 py-4">
          <h2 className="text-lg font-semibold">Review AI suggestions</h2>
          <button
            type="button"
            onClick={requestClose}
            className="text-sm text-muted-foreground hover:underline"
            data-testid="ai-review-close"
          >
            Close
          </button>
        </header>

        <div
          data-testid="ai-review-banner"
          className="flex items-center justify-between border-b bg-orange-50/60 px-6 py-3 text-sm"
        >
          <span>
            <span className="mr-1">⚡</span>
            <span data-testid="ai-review-pending-count" className="font-semibold">
              {pendingCount}
            </span>{" "}
            AI suggestion{pendingCount === 1 ? "" : "s"} awaiting review
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => applyToAll(true)}
              data-testid="ai-review-accept-all"
              className="rounded-md border border-input bg-background px-3 py-1 text-xs font-medium hover:bg-green-50"
            >
              ✓ Accept all
            </button>
            <button
              type="button"
              onClick={() => applyToAll(false)}
              data-testid="ai-review-reject-all"
              className="rounded-md border border-input bg-background px-3 py-1 text-xs font-medium hover:bg-red-50"
            >
              ✕ Reject all
            </button>
          </div>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto p-6">
          {groups.length === 0 && (
            <p className="text-sm text-muted-foreground">
              The model returned no groups. Try refining the prompt.
            </p>
          )}
          {groups.map((g) => (
            <GroupNode
              key={g.temp_id ?? g.title}
              node={g}
              selection={selection}
              edits={edits}
              editingId={editingId}
              setNode={setNode}
              setSubtree={setSubtree}
              setCompetenceSubtree={setCompetenceSubtree}
              startEdit={(id) => setEditingId(id)}
              cancelEdit={() => setEditingId(null)}
              saveEdit={saveEdit}
            />
          ))}
        </div>
        <footer className="flex justify-end gap-2 border-t px-6 py-4">
          <button
            type="button"
            onClick={requestClose}
            className="rounded-md border px-4 py-2 text-sm"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleApply}
            disabled={applying}
            data-testid="ai-review-apply"
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {applying ? "Applying…" : "Apply selection"}
          </button>
        </footer>
      </div>
    </div>
  );
}

interface RowChromeProps {
  state: NodeState;
  title: string;
  /** Decorative prefix shown before the title (e.g. `[Basic]` for indicators).
   *  Excluded from the edit input — users only rename the title itself. */
  prefix?: string;
  isEditing: boolean;
  onAccept: () => void;
  onReject: () => void;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onSaveEdit: (title: string) => void;
  testIdPrefix: string;
}

function RowChrome({
  state,
  title,
  prefix,
  isEditing,
  onAccept,
  onReject,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  testIdPrefix,
}: RowChromeProps) {
  const [draft, setDraft] = useState(title);
  const tone =
    state === "accepted"
      ? "bg-green-50/40"
      : state === "rejected"
        ? "bg-red-50/30 opacity-60"
        : "bg-orange-50/30";
  return (
    <div
      data-testid={testIdPrefix}
      data-state={state}
      className={`flex items-center justify-between gap-2 rounded p-1 ${tone}`}
    >
      {isEditing ? (
        <div className="flex flex-1 items-center gap-2">
          <input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            data-testid={`${testIdPrefix}-edit-input`}
            className="flex-1 rounded border px-2 py-1 text-sm"
          />
          <button
            type="button"
            onClick={() => onSaveEdit(draft)}
            data-testid={`${testIdPrefix}-edit-save`}
            className="rounded bg-primary px-2 py-1 text-xs text-primary-foreground"
          >
            Save
          </button>
          <button
            type="button"
            onClick={() => {
              setDraft(title);
              onCancelEdit();
            }}
            data-testid={`${testIdPrefix}-edit-cancel`}
            className="rounded border px-2 py-1 text-xs"
          >
            Cancel
          </button>
        </div>
      ) : (
        <span className="flex flex-1 items-center gap-2 text-sm">
          {state === "pending" && (
            <span className="text-orange-600" aria-hidden>
              ⚡
            </span>
          )}
          {prefix && <span className="text-muted-foreground">{prefix}</span>}
          <span className={state === "accepted" ? "font-medium" : ""}>
            {title}
          </span>
        </span>
      )}
      {!isEditing && (
        <div className="flex gap-1">
          <button
            type="button"
            aria-label="Accept"
            onClick={onAccept}
            data-testid={`${testIdPrefix}-accept`}
            className={`rounded px-1.5 text-xs ${state === "accepted" ? "bg-green-600 text-white" : "border hover:bg-green-50"}`}
          >
            ✓
          </button>
          <button
            type="button"
            aria-label="Edit"
            onClick={() => {
              setDraft(title);
              onStartEdit();
            }}
            data-testid={`${testIdPrefix}-edit`}
            className="rounded border px-1.5 text-xs hover:bg-accent"
          >
            ✎
          </button>
          <button
            type="button"
            aria-label="Reject"
            onClick={onReject}
            data-testid={`${testIdPrefix}-reject`}
            className={`rounded px-1.5 text-xs ${state === "rejected" ? "bg-red-600 text-white" : "border hover:bg-red-50"}`}
          >
            ✕
          </button>
        </div>
      )}
    </div>
  );
}

interface NodeCommonProps {
  selection: Selection;
  edits: Edits;
  editingId: string | null;
  setNode: (id: string, v: boolean) => void;
  setSubtree: (g: GeneratedGroup, v: boolean) => void;
  setCompetenceSubtree: (c: GeneratedCompetence, v: boolean) => void;
  startEdit: (id: string) => void;
  cancelEdit: () => void;
  saveEdit: (id: string, title: string) => void;
}

function GroupNode({ node, ...props }: { node: GeneratedGroup } & NodeCommonProps) {
  const id = node.temp_id ?? "";
  const state = id ? stateOf(id, props.selection) : "pending";
  const displayTitle = id && props.edits[id]?.title ? props.edits[id].title : node.title;
  return (
    <div className="rounded border p-3" data-testid="ai-review-group">
      <RowChrome
        state={state}
        title={displayTitle}
        isEditing={props.editingId === id && id !== ""}
        onAccept={() => props.setSubtree(node, true)}
        onReject={() => props.setSubtree(node, false)}
        onStartEdit={() => id && props.startEdit(id)}
        onCancelEdit={props.cancelEdit}
        onSaveEdit={(title) => id && props.saveEdit(id, title)}
        testIdPrefix="ai-review-group-row"
      />
      {node.description && (
        <p className="ml-6 text-xs text-muted-foreground">{node.description}</p>
      )}
      <div className="ml-4 mt-2 space-y-2">
        {(node.competences ?? []).map((c) => (
          <CompetenceNode key={c.temp_id ?? c.title} comp={c} {...props} />
        ))}
        {(node.children ?? []).map((sub) => (
          <GroupNode key={sub.temp_id ?? sub.title} node={sub} {...props} />
        ))}
      </div>
    </div>
  );
}

function CompetenceNode({
  comp,
  ...props
}: { comp: GeneratedCompetence } & NodeCommonProps) {
  const id = comp.temp_id ?? "";
  const state = id ? stateOf(id, props.selection) : "pending";
  const displayTitle = id && props.edits[id]?.title ? props.edits[id].title : comp.title;
  return (
    <div className="rounded border p-2" data-testid="ai-review-competence">
      <RowChrome
        state={state}
        title={displayTitle}
        isEditing={props.editingId === id && id !== ""}
        onAccept={() => props.setCompetenceSubtree(comp, true)}
        onReject={() => props.setCompetenceSubtree(comp, false)}
        onStartEdit={() => id && props.startEdit(id)}
        onCancelEdit={props.cancelEdit}
        onSaveEdit={(title) => id && props.saveEdit(id, title)}
        testIdPrefix="ai-review-competence-row"
      />
      {comp.grade_levels && Object.keys(comp.grade_levels).length > 0 && (
        <ul className="ml-6 mt-1 text-xs text-muted-foreground">
          {Object.entries(comp.grade_levels).map(([grade, lvl]) => (
            <li key={grade}>
              {grade}: <span className="text-foreground">{lvl}</span>
            </li>
          ))}
        </ul>
      )}
      {comp.indicators && comp.indicators.length > 0 && (
        <ul className="ml-6 mt-1 space-y-1 text-xs">
          {comp.indicators.map((ind: GeneratedIndicator) => (
            <IndicatorRow key={ind.temp_id ?? ind.title} ind={ind} {...props} />
          ))}
        </ul>
      )}
    </div>
  );
}

function IndicatorRow({
  ind,
  ...props
}: { ind: GeneratedIndicator } & NodeCommonProps) {
  const id = ind.temp_id ?? "";
  const state = id ? stateOf(id, props.selection) : "pending";
  const displayTitle = id && props.edits[id]?.title ? props.edits[id].title : ind.title;
  return (
    <li>
      <RowChrome
        state={state}
        title={displayTitle}
        prefix={`[${ind.skill_level}]`}
        isEditing={props.editingId === id && id !== ""}
        onAccept={() => id && props.setNode(id, true)}
        onReject={() => id && props.setNode(id, false)}
        onStartEdit={() => id && props.startEdit(id)}
        onCancelEdit={props.cancelEdit}
        onSaveEdit={(title) => id && props.saveEdit(id, title)}
        testIdPrefix="ai-review-indicator-row"
      />
    </li>
  );
}
