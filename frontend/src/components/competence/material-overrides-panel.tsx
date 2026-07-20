"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { EyeOff, Layers, Plus, RotateCcw } from "lucide-react";
import { toast } from "sonner";

import { specializationsApi } from "@/lib/api/specializations";
import type { SpecializationListItem } from "@/lib/api/specializations";
import { materialOverridesApi } from "@/lib/api/material-overrides";
import type {
  Material,
  MaterialInContext,
  MaterialOverride,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type Props = {
  competenceId: string;
  baseMaterials: Material[];
  canEdit: boolean;
};

const BASE_VALUE = "__base__";

export function MaterialOverridesPanel({
  competenceId,
  baseMaterials,
  canEdit,
}: Props) {
  const [specializations, setSpecializations] = useState<
    SpecializationListItem[]
  >([]);
  const [contextSpecId, setContextSpecId] = useState<string>(BASE_VALUE);
  const [contextMaterials, setContextMaterials] = useState<MaterialInContext[]>(
    [],
  );
  const [overrides, setOverrides] = useState<MaterialOverride[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [pendingMaterialId, setPendingMaterialId] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    specializationsApi
      .list()
      .then((items) => {
        if (!cancelled) setSpecializations(items);
      })
      .catch(() => {
        // best-effort: keep panel usable without spec list
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const reload = useCallback(async () => {
    if (contextSpecId === BASE_VALUE) {
      setContextMaterials([]);
      setOverrides([]);
      return;
    }
    setLoading(true);
    try {
      const [mats, ovs] = await Promise.all([
        materialOverridesApi.listMaterials(competenceId, contextSpecId),
        materialOverridesApi.listOverrides(competenceId, contextSpecId),
      ]);
      setContextMaterials(mats);
      setOverrides(ovs);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to load overrides",
      );
    } finally {
      setLoading(false);
    }
  }, [competenceId, contextSpecId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const hideOverrideByMaterial = useMemo(() => {
    const m = new Map<string, MaterialOverride>();
    for (const o of overrides) {
      if (o.mode === "hide") m.set(o.material_id, o);
    }
    return m;
  }, [overrides]);

  const addOverrideByMaterial = useMemo(() => {
    const m = new Map<string, MaterialOverride>();
    for (const o of overrides) {
      if (o.mode === "add") m.set(o.material_id, o);
    }
    return m;
  }, [overrides]);

  const baseIds = useMemo(
    () => new Set(baseMaterials.map((m) => m.id)),
    [baseMaterials],
  );

  const hiddenMaterials = useMemo(
    () =>
      baseMaterials.filter((m) => hideOverrideByMaterial.has(m.id)),
    [baseMaterials, hideOverrideByMaterial],
  );

  // Materials available for «Add to context» — materials that exist on the
  // competence but are not currently visible in this context (not part of
  // contextMaterials).
  const addableMaterials = useMemo(() => {
    const visibleIds = new Set(contextMaterials.map((m) => m.id));
    return baseMaterials.filter(
      (m) => !visibleIds.has(m.id) && !hideOverrideByMaterial.has(m.id),
    );
  }, [baseMaterials, contextMaterials, hideOverrideByMaterial]);

  const selectedSpecLabel = useMemo(() => {
    if (contextSpecId === BASE_VALUE) return "Base";
    return (
      specializations.find((s) => s.id === contextSpecId)?.title ?? "Context"
    );
  }, [contextSpecId, specializations]);

  async function hideMaterial(materialId: string) {
    if (contextSpecId === BASE_VALUE) return;
    setBusy(true);
    try {
      await materialOverridesApi.create(competenceId, {
        material_id: materialId,
        specialization_id: contextSpecId,
        mode: "hide",
      });
      toast.success(`Hidden in ${selectedSpecLabel}`);
      await reload();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to hide");
    } finally {
      setBusy(false);
    }
  }

  async function addMaterial(materialId: string) {
    if (contextSpecId === BASE_VALUE || !materialId) return;
    setBusy(true);
    try {
      await materialOverridesApi.create(competenceId, {
        material_id: materialId,
        specialization_id: contextSpecId,
        mode: "add",
      });
      toast.success(`Added in ${selectedSpecLabel}`);
      setAddDialogOpen(false);
      setPendingMaterialId("");
      await reload();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to add");
    } finally {
      setBusy(false);
    }
  }

  async function restoreOverride(overrideId: string) {
    setBusy(true);
    try {
      await materialOverridesApi.remove(competenceId, overrideId);
      toast.success("Default restored");
      await reload();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to restore");
    } finally {
      setBusy(false);
    }
  }

  const isBase = contextSpecId === BASE_VALUE;

  return (
    <Card data-testid="materials-overrides-panel">
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div className="flex items-start gap-2">
          <span className="mt-0.5 inline-flex size-7 items-center justify-center rounded-md bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-200">
            <Layers className="size-4" aria-hidden />
          </span>
          <div className="space-y-1">
            <CardTitle>Materials by context</CardTitle>
            <p className="text-xs text-muted-foreground">
              Pick a specialization to see how the material set looks for that
              profile and manage hide / add overrides.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!isBase && (
            <Badge
              variant="secondary"
              className="gap-1 border border-violet-200 bg-violet-50 text-violet-800 dark:border-violet-900 dark:bg-violet-950 dark:text-violet-200"
              data-testid="materials-context-active-badge"
            >
              Context: {selectedSpecLabel}
            </Badge>
          )}
          <Label className="text-xs text-muted-foreground" htmlFor="context-spec">
            Context
          </Label>
          <Select value={contextSpecId} onValueChange={setContextSpecId}>
            <SelectTrigger
              id="context-spec"
              className="h-8 w-56"
              data-testid="materials-context-select"
            >
              <SelectValue placeholder="Pick context">
                {selectedSpecLabel}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={BASE_VALUE}>Base</SelectItem>
              {specializations.map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {s.title}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {!isBase && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setContextSpecId(BASE_VALUE)}
              data-testid="materials-context-reset"
            >
              <RotateCcw className="mr-1 size-3.5" />
              Reset to Base
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {isBase ? (
          <p className="text-sm text-muted-foreground">
            Pick a specialization to see how the material set looks for
            employees of that profile and to manage hide / add overrides.
          </p>
        ) : loading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm text-muted-foreground">
                In context of <span className="font-medium">{selectedSpecLabel}</span>
                {" — "}
                {contextMaterials.length} visible · {hiddenMaterials.length} hidden
              </p>
              {canEdit && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setPendingMaterialId("");
                    setAddDialogOpen(true);
                  }}
                  disabled={busy || addableMaterials.length === 0}
                  data-testid="material-override-btn-add"
                >
                  <Plus className="mr-1 size-3.5" />
                  Add to context
                </Button>
              )}
            </div>

            {contextMaterials.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No materials visible in this context.
              </p>
            ) : (
              <ul className="space-y-1">
                {contextMaterials.map((mat) => {
                  const isAdded = mat.source === "added" || !baseIds.has(mat.id);
                  const addOv = addOverrideByMaterial.get(mat.id);
                  return (
                    <li
                      key={mat.id}
                      data-testid={`material-override-row-${mat.id}`}
                      className="flex items-center gap-2 rounded-md border bg-background px-2 py-1.5"
                    >
                      <span className="flex-1 text-sm">{mat.title}</span>
                      {isAdded && (
                        <Badge
                          variant="secondary"
                          className="text-xs"
                          data-testid={`material-override-badge-added-${mat.id}`}
                        >
                          Added in context
                        </Badge>
                      )}
                      {canEdit && (
                        <>
                          {isAdded && addOv ? (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => restoreOverride(addOv.id)}
                              disabled={busy}
                              data-testid={`material-override-btn-restore-${mat.id}`}
                            >
                              <RotateCcw className="mr-1 size-3.5" />
                              Restore default
                            </Button>
                          ) : (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => hideMaterial(mat.id)}
                              disabled={busy}
                              data-testid={`material-override-btn-hide-${mat.id}`}
                            >
                              <EyeOff className="mr-1 size-3.5" />
                              Hide in context
                            </Button>
                          )}
                        </>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}

            {hiddenMaterials.length > 0 && (
              <div
                className="space-y-1 rounded-md border border-dashed p-2"
                data-testid="material-override-hidden-list"
              >
                <p className="text-xs font-medium text-muted-foreground">
                  Hidden in this context
                </p>
                <ul className="space-y-1">
                  {hiddenMaterials.map((mat) => {
                    const ov = hideOverrideByMaterial.get(mat.id);
                    return (
                      <li
                        key={mat.id}
                        data-testid={`material-override-hidden-row-${mat.id}`}
                        className="flex items-center gap-2 text-sm text-muted-foreground"
                      >
                        <span className="flex-1 line-through">{mat.title}</span>
                        {canEdit && ov && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => restoreOverride(ov.id)}
                            disabled={busy}
                            data-testid={`material-override-btn-restore-${mat.id}`}
                          >
                            <RotateCcw className="mr-1 size-3.5" />
                            Restore default
                          </Button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
          </>
        )}
      </CardContent>

      <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
        <DialogContent data-testid="material-override-add-dialog">
          <DialogHeader>
            <DialogTitle>Add material to {selectedSpecLabel}</DialogTitle>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="material-override-pick">Material</Label>
            <Select
              value={pendingMaterialId}
              onValueChange={setPendingMaterialId}
            >
              <SelectTrigger
                id="material-override-pick"
                data-testid="material-override-add-select"
              >
                <SelectValue placeholder="Pick a material">
                  {addableMaterials.find((m) => m.id === pendingMaterialId)
                    ?.title ?? undefined}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {addableMaterials.map((m) => (
                  <SelectItem key={m.id} value={m.id}>
                    {m.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {addableMaterials.length === 0 && (
              <p className="text-xs text-muted-foreground">
                Every base material is already visible in this context.
                Create a material on the competence first, then add it here.
              </p>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setAddDialogOpen(false)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button
              onClick={() => addMaterial(pendingMaterialId)}
              disabled={busy || !pendingMaterialId}
              data-testid="material-override-add-confirm"
            >
              {busy ? "Saving…" : "Add"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
