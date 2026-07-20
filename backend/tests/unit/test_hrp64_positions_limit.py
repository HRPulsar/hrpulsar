"""HRP-64: the /employees page hits `/api/positions?limit=200` so its
filter dropdown can show every position in one round-trip. The previous
`le=100` cap on the endpoint silently produced a 422, the frontend's
defensive `.catch(() => empty)` swallowed it, and the dropdown
collapsed to "No options". This test pins the new ceiling (500) and
keeps a regression guard on the 501 case so we don't open the door
wide enough for someone to dump the whole table at once.
"""

from __future__ import annotations


class TestPositionsListLimitCap:
    async def test_limit_200_is_accepted(self, auth_client):
        # The exact value the Employees page sends. Before HRP-64 this 422'd.
        response = await auth_client.get("/api/positions?limit=200")
        assert response.status_code == 200, response.text
        body = response.json()
        assert "items" in body
        assert "total" in body

    async def test_limit_500_is_accepted(self, auth_client):
        response = await auth_client.get("/api/positions?limit=500")
        assert response.status_code == 200, response.text

    async def test_limit_above_cap_is_rejected(self, auth_client):
        # `le=500` keeps the door from sliding open all the way.
        response = await auth_client.get("/api/positions?limit=501")
        assert response.status_code == 422
