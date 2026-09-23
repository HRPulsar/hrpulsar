"""The agent setup bundle of a container (HRP-866, W6-10).

After a breakdown the company holds a verdict per step and a ``SKILL.md``
per step, and is left with the question none of them answers: which agents
to set up for this work, in what order, and what to do with the files. The
bundle is that answer as a download - every ready ``SKILL.md`` of the steps
an agent takes, plus a ``README.md`` naming the agent types, the steps
behind each and the order of actions.

Nothing here calls a model or writes a row: the README is assembled from
the coverage the screen already shows (``coverage.compute``), so the two
cannot disagree, and the skills are the stored files - a download never
starts a generation and is not a billed action.

The README is written in the tenant's content language, the one the skill
files in the same archive were generated in, through the backend catalogs
(``work_bundle.*``); a language without a catalog reads in English.

English only: this file reaches the public tree.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.i18n import translate
from app.modules.ai_settings import service as ai_settings_service
from app.modules.work import coverage
from app.modules.work.models import WorkStepSkill
from app.modules.work.skills import slugify

ARCHIVE_NAME = "agent-skills.zip"


def agent_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The steps an agent takes, grouped by agent type - the number of
    groups is how many agents the company has to set up.

    A step is in when its verdict is ``agent`` (an agent type covers it and
    the company named no person to do it) and its mode is one an agent
    produces work in - the "moves to an agent" and "moves to review"
    buckets. Groups go by the yearly hours behind them, largest first; the
    first step's position settles a tie, so the order is the same on every
    read. The hours are what the group frees - a step that goes to
    review keeps its checker's share with people (HRP-861), so the
    figure never promises more than the summary does.
    ``frontend/.../agent-guide.tsx::agentGroups`` is the same rule.
    """
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        agent = row["agent"]
        if (
            row["verdict"] != "agent"
            or not agent
            or not agent["pack_code"]
            or row["mode"] not in coverage.CANDIDATE_MODES
        ):
            continue
        group = groups.setdefault(
            agent["pack_code"],
            {
                "pack_code": agent["pack_code"],
                "agent_names": set(),
                "steps": [],
                "hours": 0.0,
            },
        )
        group["steps"].append(row)
        group["hours"] += coverage.freed_hours(row)
        if agent["agent_name"]:
            group["agent_names"].add(agent["agent_name"])
    for group in groups.values():
        group["steps"].sort(key=lambda r: r["position"])
    return sorted(
        groups.values(), key=lambda g: (-g["hours"], g["steps"][0]["position"])
    )


def skill_paths(
    groups: list[dict[str, Any]], skill_names: dict[uuid.UUID, str | None]
) -> dict[uuid.UUID, str]:
    """Archive path of every step that has a file. The folder is the
    skill's own name - the Agent Skills format expects the two to match -
    and takes the step's position when two steps share a name, then the
    next free number: a stored name that already ends in someone else's
    position must not land on the same folder, or the archive would carry
    one ``SKILL.md`` where the README names two."""
    paths: dict[uuid.UUID, str] = {}
    taken: set[str] = set()
    for group in groups:
        for row in group["steps"]:
            if row["step_id"] not in skill_names:
                continue
            # Stored names are slugs already; slugging again keeps a path
            # separator out of the archive whatever the row holds.
            base = slugify(
                skill_names[row["step_id"]] or "", f"step-{row['position']}"
            )
            folder, suffix = base, row["position"]
            while folder in taken:
                folder = f"{base}-{suffix}"
                suffix += 1
            taken.add(folder)
            paths[row["step_id"]] = f"skills/{folder}/SKILL.md"
    return paths


def build_readme(
    title: str,
    groups: list[dict[str, Any]],
    paths: dict[uuid.UUID, str],
    pack_titles: dict[str, str],
    locale: str,
) -> str:
    lines = [
        "# " + translate("work_bundle.title", locale, title=title),
        "",
        translate("work_bundle.intro", locale, count=len(groups)),
        "",
        translate("work_bundle.pack_note", locale),
    ]
    for number, group in enumerate(groups, start=1):
        code = group["pack_code"]
        # ponytail: the pack reads by its English title - the only name the
        # backend holds; the localized labels live in the interface
        # catalog. Move them here when a second backend surface needs them.
        lines += ["", f"## {number}. {pack_titles.get(code, code)} (`{code}`)", ""]
        names = ", ".join(sorted(group["agent_names"]))
        lines.append(
            "- "
            + (
                translate("work_bundle.agent_registered", locale, name=names)
                if names
                else translate("work_bundle.agent_missing", locale)
            )
        )
        lines.append(
            "- "
            + (
                translate("work_bundle.hours", locale, hours=str(round(group["hours"])))
                if group["hours"]
                else translate("work_bundle.hours_unknown", locale)
            )
        )
        lines.append("- " + translate("work_bundle.steps", locale))
        for row in group["steps"]:
            bucket = coverage.BUCKET_OF_MODE[row["mode"]]
            mode = translate(f"work_bundle.mode_{bucket}", locale)
            path = paths.get(row["step_id"])
            lines.append(
                "  - "
                + (
                    translate(
                        "work_bundle.step_ready",
                        locale,
                        position=str(row["position"]),
                        title=row["title"],
                        mode=mode,
                        path=path,
                    )
                    if path
                    else translate(
                        "work_bundle.step_missing",
                        locale,
                        position=str(row["position"]),
                        title=row["title"],
                        mode=mode,
                    )
                )
            )

    steps = [row for group in groups for row in group["steps"]]
    todo = ["order", "install", "register"]
    if any(coverage.BUCKET_OF_MODE[row["mode"]] == "to_review" for row in steps):
        todo.append("review")
    if any(row["step_id"] not in paths for row in steps):
        todo.append("missing")
    lines += ["", "## " + translate("work_bundle.todo_heading", locale), ""]
    lines += [
        f"{number}. " + translate(f"work_bundle.todo_{item}", locale)
        for number, item in enumerate(todo, start=1)
    ]
    lines += ["", translate("work_bundle.footer", locale), ""]
    return "\n".join(lines)


def build_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, text in files.items():
            archive.writestr(path, text)
    return buffer.getvalue()


async def build(
    db: AsyncSession, tenant_id: uuid.UUID, container_id: uuid.UUID
) -> bytes:
    """The archive, or ``work_skill_not_found`` while no step of the guide
    has a ready file - the screen keeps the button disabled then."""
    # A download is a read: it must not start a competence mapping run.
    result = await coverage.compute(db, tenant_id, container_id, schedule_mapping=False)
    groups = agent_groups(result["steps"])
    # The row's status, not the table's: a file written for the pack the
    # step had before the company named another one is not ready (HRP-863).
    step_ids = [
        row["step_id"]
        for group in groups
        for row in group["steps"]
        if row["skill_status"] == "ready"
    ]
    skills = (
        (
            await db.execute(
                select(WorkStepSkill).where(
                    WorkStepSkill.step_id.in_(step_ids),
                    WorkStepSkill.status == "ready",
                    WorkStepSkill.content.is_not(None),
                )
            )
        )
        .scalars()
        .all()
        if step_ids
        else []
    )
    if not skills:
        raise AppError("work_skill_not_found", 404)

    paths = skill_paths(groups, {s.step_id: s.skill_name for s in skills})
    settings = await ai_settings_service.get_or_default(db, tenant_id)
    readme = build_readme(
        result["title"],
        groups,
        paths,
        result["pack_titles"],
        settings.content_language,
    )
    files = {"README.md": readme}
    files.update({paths[s.step_id]: s.content or "" for s in skills})
    return build_zip(files)
