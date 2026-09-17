"""Only coverage may aim a mapping run at shared (origin) competences."""

import uuid


class TestOriginMappingContract:
    async def test_coverage_enqueues_with_include_origin(self, monkeypatch):
        from app.core import task_enqueue
        from app.modules.work import coverage

        calls: list[dict] = []

        class _Client:
            async def set(self, *a, **k):
                return True

            async def delete(self, *a, **k):
                return 1

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        # Module object, not the dotted string: ``app.core`` exposes a
        # ``redis`` attribute that is not this module.
        import app.core.redis as redis_module

        monkeypatch.setattr(redis_module, "redis_client", lambda: _Client())
        monkeypatch.setattr(
            task_enqueue, "enqueue_task", lambda *a, **k: calls.append(k) or None
        )
        tenant_id = uuid.uuid4()
        assert await coverage._schedule_mapping(tenant_id, [uuid.uuid4()], None)
        assert calls and calls[0]["include_origin"] is True

    def test_task_default_excludes_origin(self):
        import inspect

        from app.modules.primitives.tasks import map_competences_task

        params = inspect.signature(map_competences_task.run).parameters
        assert params["include_origin"].default is False
