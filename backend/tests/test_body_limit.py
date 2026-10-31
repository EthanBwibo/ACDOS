"""The request body cap (#33, app/body_limit.py), driven as raw ASGI so a
false or missing Content-Length can be sent, which an HTTP client won't do."""

import asyncio
import json

from app.body_limit import BodyLimit

LIMIT = 1000
PATH = "/capped"


class App:
    """Records the body it was given."""

    def __init__(self) -> None:
        self.body: bytes | None = None

    async def __call__(self, scope, receive, send):
        chunks = []
        while True:
            message = await receive()
            chunks.append(message.get("body", b""))
            if not message.get("more_body"):
                break
        self.body = b"".join(chunks)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def call(chunks: list[bytes], content_length: str | None, path: str = PATH):
    app = App()
    capped = BodyLimit(app, {("POST", PATH): LIMIT})
    headers = [(b"content-type", b"application/json")]
    if content_length is not None:
        headers.append((b"content-length", content_length.encode()))
    scope = {"type": "http", "method": "POST", "path": path, "headers": headers}
    messages = [
        {"type": "http.request", "body": c, "more_body": i < len(chunks) - 1}
        for i, c in enumerate(chunks)
    ]
    sent = []

    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    asyncio.run(capped(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, body, app


def test_a_body_within_the_limit_reaches_the_app_unchanged():
    chunks = [b"x" * 400, b"y" * 400]
    status, _, app = call(chunks, str(800))
    assert status == 200
    assert app.body == b"".join(chunks)


def test_a_declared_content_length_over_the_limit_is_413_before_reading():
    status, body, app = call([b"x" * 10], str(LIMIT + 1))
    assert status == 413
    assert json.loads(body)["code"] == "payload_too_large"
    assert app.body is None


def test_a_false_small_content_length_is_still_capped_by_the_bytes_read():
    status, body, app = call([b"x" * 600, b"x" * 600], "10")
    assert status == 413
    assert json.loads(body)["code"] == "payload_too_large"
    assert app.body is None


def test_a_chunked_body_without_content_length_is_capped():
    status, _, app = call([b"x" * 300] * 4, None)
    assert status == 413
    assert app.body is None


def test_other_paths_are_not_capped():
    status, _, app = call([b"x" * (LIMIT * 3)], None, path="/elsewhere")
    assert status == 200
    assert len(app.body) == LIMIT * 3
