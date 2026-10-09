"""HRP-773: ``GET /v1/question-sets/sample`` passes its own response model.

The sample is a static preview with no row behind it - no id, no
candidate-vacancy, no timestamps - so it is ``QuestionSetSample`` rather
than ``QuestionSetRead``, which failed response validation on every call.
"""

from pathlib import Path

from app.main import app
from app.modules.recruitment.question_service import get_sample_question_set
from app.modules.recruitment.schemas import QuestionSetSample
from fastapi.routing import APIRoute

FRONTEND = Path(__file__).resolve().parents[3] / "frontend" / "src" / "components" / "recruitment"


def _route() -> APIRoute:
    return next(r for r in app.routes if isinstance(r, APIRoute) and r.path == "/api/v1/question-sets/sample")


def test_the_sample_payload_validates_against_the_routes_model():
    route = _route()
    assert route.response_model is QuestionSetSample
    sample = QuestionSetSample.model_validate(get_sample_question_set())
    assert sample.id is None and sample.status == "sample"
    assert sample.questions and all(q.id is None for q in sample.questions)


async def test_the_sample_answers_200(auth_client):
    resp = await auth_client.get("/api/v1/question-sets/sample")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "sample" and body["id"] is None and body["questions"]


def test_the_frontend_calls_the_routes_url():
    source = (FRONTEND / "interview-question-sets.tsx").read_text()
    assert '"/v1/question-sets/sample"' in source
    assert _route().path == "/api" + "/v1/question-sets/sample"
