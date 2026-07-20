"""HRP-59 / HRP-160: the /company and /company/divisions/{id} pages hit
`/api/employees?limit=500` (with and without a `division_id` filter) to
populate the Manager / Deputy picker and the Employees block. The
previous `le=100` cap silently produced a 422, the frontend's
`Promise.allSettled` swallowed it, and:

- the Employees block on the division page collapsed to "No employees
  in this division" (HRP-160);
- the Edit dialog's Manager / Deputy `<Select>` could not resolve the
  assignment label, so Base UI's `SelectValue` fell through to its
  serialized-value fallback and rendered the raw UUID (HRP-59).

This test pins the new ceiling (500) and keeps a regression guard on
the 501 case so we don't open the door wide enough to dump the whole
table at once.
"""

from __future__ import annotations


class TestEmployeesListLimitCap:
    async def test_limit_500_is_accepted(self, auth_client):
        # The exact value the division detail page sends. Before HRP-59
        # / HRP-160 this 422'd and silently emptied the response.
        response = await auth_client.get("/api/employees?limit=500")
        assert response.status_code == 200, response.text
        body = response.json()
        assert "items" in body
        assert "total" in body

    async def test_limit_500_with_division_filter_is_accepted(self, auth_client):
        # The exact shape used to populate the Employees block on
        # /company/divisions/{id}.
        response = await auth_client.get(
            "/api/employees?division_id=00000000-0000-0000-0000-000000000000&limit=500"
        )
        # Validates 200 (filter compiles even with a missing division)
        # rather than the prior 422 from the limit cap.
        assert response.status_code == 200, response.text

    async def test_limit_above_cap_is_rejected(self, auth_client):
        # `le=500` keeps the door from sliding open all the way.
        response = await auth_client.get("/api/employees?limit=501")
        assert response.status_code == 422
