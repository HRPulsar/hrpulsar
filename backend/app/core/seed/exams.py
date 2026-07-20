"""Step 7: mass exam with questions and per-employee attempts — full demo
only."""

import random

from sqlalchemy import select

from app.modules.exam.models import (
    Exam,
    ExamAnswer,
    ExamPassMark,
    ExamQuestion,
    MassExam,
    QuestionOption,
)

from .context import SeedContext
from .data import EXAM_QUESTIONS_DATA
from .helpers import past_dt, uid


async def seed_mass_exam(ctx: SeedContext) -> None:
    mass_exam = MassExam(
        id=uid(),
        tenant_id=ctx.tenant_id,
        title="Q1 2026 Engineering Knowledge Check",
        description="Quarterly technical assessment covering Python, SQL, and API design fundamentals.",
        initiator_id=ctx.admin_user.id,
        status="published",
        started_at=past_dt(7),
    )
    ctx.db.add(mass_exam)
    await ctx.db.flush()

    exam_questions = []
    for idx, (q_title, q_type, options) in enumerate(EXAM_QUESTIONS_DATA):
        q = ExamQuestion(
            id=uid(),
            mass_exam_id=mass_exam.id,
            title=q_title,
            question_type=q_type,
            sort_index=idx,
            weight=2 if q_type == "essay" else 1,
        )
        ctx.db.add(q)
        exam_questions.append(q)
        await ctx.db.flush()

        for oi, (opt_title, is_correct) in enumerate(options):
            ctx.db.add(
                QuestionOption(
                    id=uid(),
                    question_id=q.id,
                    title=opt_title,
                    sort_index=oi,
                    is_correct=is_correct,
                )
            )

    await ctx.db.flush()

    ctx.db.add(
        ExamPassMark(
            id=uid(),
            mass_exam_id=mass_exam.id,
            grade_id=ctx.grades["Junior"].id,
            min_score_percent=50,
        )
    )
    ctx.db.add(
        ExamPassMark(
            id=uid(),
            mass_exam_id=mass_exam.id,
            grade_id=ctx.grades["Middle"].id,
            min_score_percent=70,
        )
    )
    ctx.db.add(
        ExamPassMark(
            id=uid(),
            mass_exam_id=mass_exam.id,
            grade_id=ctx.grades["Senior"].id,
            min_score_percent=85,
        )
    )
    await ctx.db.flush()

    max_score = sum(q.weight for q in exam_questions)
    eng_employees = ctx.employees[:10]

    for emp in eng_employees:
        status = random.choice(["assigned", "completed", "completed", "in_progress"])
        exam = Exam(
            id=uid(),
            tenant_id=ctx.tenant_id,
            mass_exam_id=mass_exam.id,
            employee_id=emp.id,
            status=status if status != "completed" else "completed",
            max_score=max_score,
            started_at=past_dt(5) if status != "assigned" else None,
            finished_at=past_dt(3) if status == "completed" else None,
        )
        if status == "completed":
            exam.score = random.randint(int(max_score * 0.5), max_score)
        ctx.db.add(exam)
        await ctx.db.flush()

        if status in ("completed", "in_progress"):
            qs_to_answer = (
                exam_questions if status == "completed" else exam_questions[:4]
            )
            for q in qs_to_answer:
                if q.question_type == "essay":
                    ctx.db.add(
                        ExamAnswer(
                            id=uid(),
                            exam_id=exam.id,
                            question_id=q.id,
                            text_answer="Sample essay answer for demo purposes.",
                            score=random.randint(0, q.weight),
                        )
                    )
                else:
                    opts = (
                        (
                            await ctx.db.execute(
                                select(QuestionOption).where(
                                    QuestionOption.question_id == q.id
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    correct_ids = [o.id for o in opts if o.is_correct]
                    if random.random() > 0.3:
                        selected = [str(oid) for oid in correct_ids]
                        is_correct = True
                        score = q.weight
                    else:
                        wrong = [o.id for o in opts if not o.is_correct]
                        selected = (
                            [str(random.choice(wrong))]
                            if wrong
                            else [str(correct_ids[0])]
                        )
                        is_correct = False
                        score = 0

                    ctx.db.add(
                        ExamAnswer(
                            id=uid(),
                            exam_id=exam.id,
                            question_id=q.id,
                            selected_option_ids=selected,
                            is_correct=is_correct,
                            score=score,
                        )
                    )

    await ctx.db.flush()
