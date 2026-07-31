import json
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import billing_hooks
from app.core.errors import AppError
from app.database import get_db
from app.modules.ai import file_parsing
from app.modules.ai_competence_generation import service
from app.modules.ai_competence_generation.billing_actions import (
    refine_action_for_scope,
    start_action_for_scope,
)
from app.modules.ai_competence_generation.schemas import (
    ApplyResult,
    OtherActiveSessionRead,
    SelectionPatch,
    SelectionReplace,
    SessionApply,
    SessionCreate,
    SessionHistoryItem,
    SessionParams,
    SessionRead,
    SessionRefine,
    SessionScope,
)
from app.modules.auth.dependencies import require_role
from app.modules.auth.models import User
from app.modules.position.models import Position
from app.modules.specialization import service as spec_service

router = APIRouter(prefix="/competence-generation", tags=["ai-generation"])


def _billing_action_for_scope(scope: str) -> str:
    """Map session scope → billing action key. Thin wrapper around
    `billing_actions.start_action_for_scope` kept for backwards-compat with
    older imports."""
    return start_action_for_scope(scope)


def _refine_action_for_scope(scope: str) -> str:
    return refine_action_for_scope(scope)


def _to_read(sess) -> dict:
    return {
        "id": sess.id,
        "tenant_id": sess.tenant_id,
        "user_id": sess.user_id,
        "scope": sess.scope,
        "target_id": sess.target_id,
        "params": sess.params or {},
        "payload": sess.payload,
        "selection_state": sess.selection_state or {},
        "status": sess.status,
        "error_code": sess.error_code,
        "error_message": sess.error_message,
        "parent_session_id": sess.parent_session_id,
        "prompt_version": sess.prompt_version,
        "llm_model": sess.llm_model,
        "tokens_used": sess.tokens_used,
        "created_at": sess.created_at,
        "updated_at": sess.updated_at,
        "finished_at": sess.finished_at,
        # HRP-114 re-spec: surface the snapshot of pre-existing content so the
        # result modal can show new+existing items in the same tree.
        "existing_tree": _existing_tree_from_snapshot(sess),
        "existing_indicators": _existing_indicators_from_snapshot(sess),
    }


def _existing_tree_from_snapshot(sess) -> list[dict] | None:
    """HRP-114 re-spec: pull the snapshot tree (already-present subgroups +
    competences + indicators) so the result preview can render existing items
    alongside the newly generated ones. group scope returns the single target
    group as the tree root; whole_base returns the full library snapshot.
    Returns None when the scope has no notion of an existing tree.
    """
    snapshot = getattr(sess, "base_snapshot", None) or {}
    if sess.scope == "group":
        grp = snapshot.get("group")
        return [grp] if grp else []
    if sess.scope == "whole_base":
        return snapshot.get("groups") or []
    return None


def _existing_indicators_from_snapshot(sess) -> list[dict] | None:
    """HRP-114 re-spec: existing indicators of the target competence so the
    indicators result modal can list them as locked rows next to the new
    suggestions. Returns None for non-indicators scopes.
    """
    if sess.scope != "competence_indicators":
        return None
    snapshot = getattr(sess, "base_snapshot", None) or {}
    comp = snapshot.get("competence") or {}
    return comp.get("indicators") or []


@router.post("/sessions", response_model=SessionRead, status_code=201)
async def create_session(
    payload: SessionCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    # Precheck before persisting the session so a 402 doesn't leave a
    # stranded `pending` row that would block the per-user partial unique.
    action = _billing_action_for_scope(payload.scope)
    cost = await billing_hooks.resolve_cost(db, current_user.tenant_id, action)
    await billing_hooks.precheck_action(
        db, current_user.tenant_id, action, amount_override=cost
    )
    sess = await service.create_session(
        db, current_user.tenant_id, current_user.id, payload, cost=cost
    )
    # Kick off the worker. Use late import to keep startup graph small.
    from app.core.task_enqueue import enqueue_task
    from app.modules.ai_competence_generation.tasks import run_generation_session

    result = enqueue_task(
        run_generation_session,
        str(sess.id),
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        module="ai_competence_generation",
        action=action,
    )
    sess.celery_task_id = result.id
    await db.commit()
    await db.refresh(sess)
    response.status_code = status.HTTP_201_CREATED
    return _to_read(sess)


@router.get("/sessions", response_model=list[SessionHistoryItem])
async def list_sessions(
    target_id: uuid.UUID | None = Query(default=None),
    scope: SessionScope | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Tenant-scoped list of generation sessions for the AI history tab.

    The expensive `payload` JSON is intentionally omitted; counts are derived
    server-side from `selection_state` (or `applied_result` for terminal-applied
    rows). Filter by `target_id` (e.g. specialization id) and/or `scope`.
    """
    return await service.list_sessions(
        db,
        tenant_id=current_user.tenant_id,
        target_id=target_id,
        scope=scope,
        limit=limit,
        offset=offset,
    )


@router.get("/sessions/active", response_model=SessionRead | None)
async def get_active(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    sess = await service.get_active_session(db, current_user.id)
    return _to_read(sess) if sess else None


@router.get("/context-options")
async def context_options(
    scope: SessionScope = Query(...),
    target_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """HRP-143: lists the tenant data the preflight modal can drop into
    ``context_excludes``. Used by the whole_base / group / indicators
    confirmation dialogs to render per-item chips with × controls.

    Shape:
    ``{
        "specializations": [{"id", "title"}, ...],
        "divisions": [{"id", "name"}, ...],
        "company_description": str | null,
        "source_tree": [...]   // only for whole_base / group scopes
    }``
    """
    return await service.list_context_options(
        db,
        current_user.tenant_id,
        scope=scope,
        target_id=target_id,
    )


@router.get(
    "/sessions/active-others",
    response_model=list[OtherActiveSessionRead],
)
async def list_active_others(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Active generation sessions belonging to *other* tenant users (PreflightModal)."""
    return await service.list_other_active_sessions(
        db, tenant_id=current_user.tenant_id, user_id=current_user.id
    )


@router.get("/sessions/{session_id}", response_model=SessionRead)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    # Tenant-wide visibility for the history tab (HRP-71): any admin in the
    # tenant can open any session read-only. Write-paths still require
    # ownership via service.get_session (see refine/regenerate/apply/cancel).
    sess = await service.get_session_for_view(
        db, session_id, tenant_id=current_user.tenant_id
    )
    return _to_read(sess)


@router.patch("/sessions/{session_id}/selection", response_model=SessionRead)
async def patch_selection(
    session_id: uuid.UUID,
    patch: SelectionPatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    sess = await service.update_selection(
        db,
        session_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        node_id=patch.node_id,
        selected=patch.selected,
    )
    return _to_read(sess)


@router.put("/sessions/{session_id}/selection-state", response_model=SessionRead)
async def put_selection_state(
    session_id: uuid.UUID,
    body: SelectionReplace,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    sess = await service.replace_selection(
        db,
        session_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        selection_state=body.selection_state,
        edits={tid: edit.model_dump() for tid, edit in body.edits.items()},
    )
    return _to_read(sess)


@router.post(
    "/sessions/{session_id}/refine", response_model=SessionRead, status_code=201
)
async def refine_session(
    session_id: uuid.UUID,
    refine: SessionRefine,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    # Refine cost is constant per call (one LLM round on a smaller context),
    # but specialization_matrix sessions bill from their own pricing
    # category — look at the parent's scope to pick the right action.
    parent = await service.get_session(
        db,
        session_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
    )
    refine_action = _refine_action_for_scope(parent.scope)
    cost = await billing_hooks.resolve_cost(db, current_user.tenant_id, refine_action)
    await billing_hooks.precheck_action(
        db,
        current_user.tenant_id,
        refine_action,
        amount_override=cost,
    )
    child = await service.refine_session(
        db,
        session_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        refine=refine,
        cost=cost,
    )
    from app.core.task_enqueue import enqueue_task
    from app.modules.ai_competence_generation.tasks import run_generation_session

    result = enqueue_task(
        run_generation_session,
        str(child.id),
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        module="ai_competence_generation",
        action="refine",
    )
    child.celery_task_id = result.id
    await db.commit()
    await db.refresh(child)
    return _to_read(child)


@router.post(
    "/sessions/{session_id}/regenerate",
    response_model=SessionRead,
    status_code=201,
)
async def regenerate_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    # Regenerate inherits the parent's billing intent: re-running a refine
    # is a refine-priced call; re-running an initial generation is start-priced.
    parent = await service.get_session(
        db,
        session_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
    )
    parent_action = (parent.params or {}).get(
        "billing_action"
    ) or _billing_action_for_scope(parent.scope)
    cost = await billing_hooks.resolve_cost(db, current_user.tenant_id, parent_action)
    await billing_hooks.precheck_action(
        db, current_user.tenant_id, parent_action, amount_override=cost
    )

    child = await service.regenerate_session(
        db,
        session_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        cost=cost,
    )
    from app.core.task_enqueue import enqueue_task
    from app.modules.ai_competence_generation.tasks import run_generation_session

    result = enqueue_task(
        run_generation_session,
        str(child.id),
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        module="ai_competence_generation",
        action="regenerate",
    )
    child.celery_task_id = result.id
    await db.commit()
    await db.refresh(child)
    return _to_read(child)


@router.post("/sessions/{session_id}/apply", response_model=ApplyResult)
async def apply_session(
    session_id: uuid.UUID,
    body: SessionApply,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await service.apply_session(
        db,
        session_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        publish=body.publish,
        idempotency_key=body.idempotency_key,
        actor_id=current_user.id,
    )
    return result


@router.delete("/sessions/{session_id}", response_model=SessionRead)
async def cancel_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    sess = await service.cancel_session(
        db,
        session_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
    )
    return _to_read(sess)


@router.post("/sessions/{session_id}/clear", response_model=SessionRead)
async def clear_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    sess = await service.clear_payload(
        db,
        session_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
    )
    return _to_read(sess)


# ---------------------------------------------------------------------------
# specialization_matrix scope — multipart form (text inputs + uploaded files)
# ---------------------------------------------------------------------------


@router.post(
    "/specialization-matrix-sessions",
    response_model=SessionRead,
    status_code=201,
)
async def create_matrix_session(
    response: Response,
    target_id: uuid.UUID | None = Form(None),
    position_id: uuid.UUID | None = Form(None),
    grade_ids: str | None = Form(None),
    responsibilities: str | None = Form(None),
    daily_tasks: str | None = Form(None),
    weekly_tasks: str | None = Form(None),
    kpi: str | None = Form(None),
    requirements_text: str | None = Form(None),
    # HRP-119 AC2: caller flips this on (only meaningful when the existing
    # matrix has competences) to ask the LLM to extend every existing
    # competence with extra indicators in the same response.
    indicators_for_existing: bool = Form(False),
    # HRP-159: preflight context — JSON list of excludes (categories or
    # per-item keys like "position:<uuid>" / "division:<uuid>" /
    # "competence:<uuid>") and a free-form refinement note.
    context_excludes: str | None = Form(None),
    refinement_prompt: str | None = Form(None),
    files: list[UploadFile] = File(default_factory=list),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Start an AI generation for a specialization's competence matrix.

    Multipart form: text fields above + zero-or-more files. Files are parsed
    synchronously here so the user gets a clean 400 on `.doc` or oversized
    inputs before any LLM credit is spent. Whitelist + limits live in
    `app.modules.ai.file_parsing`.

    `position_id` (HRP-33) lets the client launch the same matrix flow from a
    Position page: `target_id` is resolved from `position.specialization_id`
    when only `position_id` is sent. The session row carries `position_id`
    in `params` so apply can collapse all generated competences under a
    single group named after the position.

    `grade_ids` (HRP-57 P2) is a JSON-encoded list of grade UUIDs the user
    selected in the brief. Pairs are pre-created via the same idempotent
    bulk-add path the manual flow uses, so AI runs against the same set of
    grades the user picked. For Position-launched flows, the position's
    own grade is auto-included so the matrix at least covers the active
    role even if the user didn't expand the multi-select.
    """

    if target_id is None and position_id is None:
        raise AppError(
            "compgen_target_or_position_required",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    parsed_grade_ids: list[uuid.UUID] = []
    if grade_ids:
        try:
            raw = json.loads(grade_ids)
        except (TypeError, ValueError) as exc:
            raise AppError(
                "compgen_grade_ids_invalid",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            ) from exc
        if not isinstance(raw, list):
            raise AppError(
                "compgen_grade_ids_invalid",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        try:
            parsed_grade_ids = [uuid.UUID(str(v)) for v in raw]
        except (TypeError, ValueError) as exc:
            raise AppError(
                "compgen_grade_ids_invalid",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            ) from exc

    parsed_context_excludes: list[str] = []
    if context_excludes:
        try:
            raw_ex = json.loads(context_excludes)
        except (TypeError, ValueError) as exc:
            raise AppError(
                "compgen_context_excludes_invalid",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            ) from exc
        if not isinstance(raw_ex, list) or not all(
            isinstance(v, str) for v in raw_ex
        ):
            raise AppError(
                "compgen_context_excludes_invalid",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        parsed_context_excludes = list(raw_ex)

    position_title: str | None = None
    if position_id is not None:
        position = await db.get(Position, position_id)
        if position is None or position.tenant_id != current_user.tenant_id:
            raise AppError("position_not_found", status.HTTP_404_NOT_FOUND)
        if position.specialization_id is None:
            raise AppError(
                "insufficient_data_no_position_specialization",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail_extra={},
                detail_code_key="error_code",
                detail_code="insufficient_data",
            )
        if target_id is None:
            target_id = position.specialization_id
        elif target_id != position.specialization_id:
            # Caller sent both fields but they disagree — refuse rather than
            # silently honour `target_id` and add the position's grade to a
            # different specialization.
            raise AppError(
                "compgen_target_id_position_mismatch",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        # Position page: cover the position's own grade by default so the
        # active role is guaranteed a matrix slot even if the user shipped
        # the brief without touching the grades multi-select.
        if position.grade_id is not None and position.grade_id not in parsed_grade_ids:
            parsed_grade_ids.append(position.grade_id)
        position_title = position.title

    # By this point `target_id` has been set either directly, from
    # `position.specialization_id`, or both (and validated to match). The
    # initial `if target_id is None and position_id is None` guard
    # rejects the only remaining unset case, but mypy can't follow that
    # — pin it explicitly.
    assert target_id is not None

    # Pre-create Spec×Grade pairs so `_ensure_specialization_accessible`
    # passes and `_apply_specialization_matrix` has rows to write links to.
    # `add_grades` is idempotent on the (spec, grade) unique constraint.
    if parsed_grade_ids:
        await spec_service.add_grades(
            db, current_user.tenant_id, target_id, parsed_grade_ids
        )

    raw_files: list[tuple[str, bytes]] = []
    for upload in files:
        if upload.filename is None:
            continue
        content = await upload.read()
        raw_files.append((upload.filename, content))

    try:
        parsed_text = file_parsing.parse_files(raw_files) if raw_files else ""
    except file_parsing.UnsupportedFileError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except file_parsing.FileParseError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    action = start_action_for_scope("specialization_matrix")
    cost = await billing_hooks.resolve_cost(db, current_user.tenant_id, action)
    await billing_hooks.precheck_action(
        db, current_user.tenant_id, action, amount_override=cost
    )

    payload = SessionCreate(
        scope="specialization_matrix",
        target_id=target_id,
        params=SessionParams(
            refinement_prompt=refinement_prompt,
            context_excludes=parsed_context_excludes,
        ),
    )
    sess = await service.create_session(
        db,
        current_user.tenant_id,
        current_user.id,
        payload,
        cost=cost,
        extra_params={
            "responsibilities": responsibilities,
            "daily_tasks": daily_tasks,
            "weekly_tasks": weekly_tasks,
            "kpi": kpi,
            "requirements_text": requirements_text,
            "parsed_files": parsed_text or None,
            "uploaded_filenames": [name for name, _ in raw_files],
            "position_id": str(position_id) if position_id else None,
            "position_title": position_title,
            "grade_ids": [str(gid) for gid in parsed_grade_ids] or None,
            "indicators_for_existing": indicators_for_existing,
        },
    )

    from app.core.task_enqueue import enqueue_task
    from app.modules.ai_competence_generation.tasks import run_generation_session

    result = enqueue_task(
        run_generation_session,
        str(sess.id),
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        module="ai_competence_generation",
        action=action,
    )
    sess.celery_task_id = result.id
    await db.commit()
    await db.refresh(sess)
    response.status_code = status.HTTP_201_CREATED
    return _to_read(sess)
