"""Celery tasks for the recruitment module.

Split from the former single-file ``tasks.py`` monolith (project-review #20)
into concern modules:

- ``parsing`` — resume parsing + text extraction
- ``generation`` — candidate questions / vacancy profile generation
- ``analysis`` — interview transcription + AI analysis (full / resume-only)
- ``reporting`` — consolidated report generation
- ``av_scan`` — interview media antivirus scan
- ``maintenance`` — periodic cleanup sweepers + the task_failure handler
- ``gdpr`` — GDPR export worker
- ``demo_analysis`` — demo-killswitch seed-based analysis helpers

Every task decorator pins ``name="app.modules.recruitment.tasks.<fn>"`` — the
pre-split names are a public contract (beat schedule in
``app/core/celery_app.py``, ``_RECRUITMENT_STATUS_MAP`` in ``maintenance``,
messages already sitting in the broker queue). Keep new tasks in the same
namespace.

The task objects are re-exported here so ``from
app.modules.recruitment.tasks import <task>`` keeps working; importing this
package also registers the ``task_failure`` signal handler (``maintenance``).
Internal ``_``-prefixed helpers are NOT re-exported — import them from their
canonical submodule.
"""

from app.modules.recruitment.tasks.analysis import (
    analyze_interview_task,
    analyze_resume_only_task,
    transcribe_interview_task,
)
from app.modules.recruitment.tasks.av_scan import scan_interview_media_task
from app.modules.recruitment.tasks.gdpr import run_gdpr_export_task
from app.modules.recruitment.tasks.generation import (
    generate_profile_task,
    generate_questions_task,
)
from app.modules.recruitment.tasks.maintenance import (
    cleanup_detached_resume_files_task,
    cleanup_orphan_upload_sessions_task,
    cleanup_stuck_recruitment_tasks_task,
    purge_archived_interviews_task,
)
from app.modules.recruitment.tasks.parsing import parse_resume_task
from app.modules.recruitment.tasks.reporting import generate_report_task

__all__ = [
    "analyze_interview_task",
    "analyze_resume_only_task",
    "cleanup_detached_resume_files_task",
    "cleanup_orphan_upload_sessions_task",
    "cleanup_stuck_recruitment_tasks_task",
    "generate_profile_task",
    "generate_questions_task",
    "generate_report_task",
    "parse_resume_task",
    "purge_archived_interviews_task",
    "run_gdpr_export_task",
    "scan_interview_media_task",
    "transcribe_interview_task",
]
