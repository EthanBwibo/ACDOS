"""Add pickup and Set home without a CSV (#253). The contract is in
app/routers/dispatcher.py and app/models/schemas.py; the checks follow in
the next commit."""

from app.models.schemas import RejectReason


class Rejected(Exception):
    def __init__(self, reason: RejectReason, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class KeyReused(Exception):
    pass


async def crew_page(conn, q, after, limit):
    raise NotImplementedError


async def nearest_zone(conn, point):
    raise NotImplementedError


async def add_pickup(conn, body, idempotency_key, now):
    raise NotImplementedError


async def set_home(conn, crew_member_id, body):
    raise NotImplementedError
