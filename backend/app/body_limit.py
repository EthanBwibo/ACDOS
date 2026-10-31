"""A cap on request body size for chosen paths (#33), on the bytes actually
read.

FastAPI reads and parses a body before any route code or dependency runs, so
the cap has to sit in front of the app: this ASGI middleware reads the body
of a capped request itself, counting bytes as they arrive, and answers 413
payload_too_large as soon as it passes the limit, whatever Content-Length
says (or without one, chunked). A body within the limit is handed to the app
unchanged.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import ErrorBody, ErrorCode, error_response


class BodyLimit:
    def __init__(self, app: ASGIApp, limits: dict[tuple[str, str], int]) -> None:
        self.app = app
        self.limits = limits  # (method, path) -> max bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = (
            self.limits.get((scope["method"], scope["path"])) if scope["type"] == "http" else None
        )
        if limit is None:
            await self.app(scope, receive, send)
            return

        too_large = ErrorBody(
            code=ErrorCode.PAYLOAD_TOO_LARGE, detail=f"the request body is over {limit} bytes"
        )
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await error_response(413, too_large)(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            if len(body) > limit:
                await error_response(413, too_large)(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
