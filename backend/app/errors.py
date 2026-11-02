"""One error body for every 4xx and 5xx the API sends (#122).

    {"code": "unknown_ids", "detail": "...", "pickup_request_ids": [...], "vehicle_ids": [...]}

code is a stable machine value from ErrorCode (an enum in the OpenAPI
contract, so the app can switch on it); detail is for people. The id lists
appear only when the error is about ids. FastAPI's own errors (request
validation, an unknown path) are turned into the same body here, so a
client never sees another shape.

Routes declare which errors they send with errors(...), which puts each
status's codes in the contract (docs/openapi.json) as x-error-codes;
tests/test_contract.py makes every route produce every code it declares and
checks the body.
"""

from enum import StrEnum
from http import HTTPStatus
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic.json_schema import SkipJsonSchema
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorCode(StrEnum):
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    UNAVAILABLE = "unavailable"
    VALIDATION_FAILED = "validation_failed"
    IDEMPOTENCY_KEY_REUSED = "idempotency_key_reused"
    DUPLICATE_IDS = "duplicate_ids"
    UNKNOWN_IDS = "unknown_ids"
    NOT_PLANNABLE = "not_plannable"
    DEPARTED_ROUTES = "departed_routes"
    VEHICLES_ON_DEPARTED_ROUTES = "vehicles_on_departed_routes"
    # Pickup-event upload (#33): the whole request, then one event.
    PAYLOAD_TOO_LARGE = "payload_too_large"
    DRIVER_MISMATCH = "driver_mismatch"
    NOT_YOUR_STOP = "not_your_stop"
    ALREADY_CONFIRMED = "already_confirmed"


class ErrorBody(BaseModel):
    code: ErrorCode
    detail: str
    # Only for errors about ids; otherwise left out of the body, never null,
    # so the contract shows them as optional arrays (None hidden from it).
    pickup_request_ids: list[UUID] | SkipJsonSchema[None] = None
    vehicle_ids: list[UUID] | SkipJsonSchema[None] = None


class ApiError(Exception):
    """Raised by routes and dependencies; sent as an ErrorBody."""

    def __init__(
        self,
        status: int,
        code: ErrorCode,
        detail: str,
        *,
        pickup_request_ids: list[UUID] | None = None,
        vehicle_ids: list[UUID] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.body = ErrorBody(
            code=code,
            detail=detail,
            pickup_request_ids=sorted(pickup_request_ids, key=str) if pickup_request_ids else None,
            vehicle_ids=sorted(vehicle_ids, key=str) if vehicle_ids else None,
        )
        self.headers = headers


def error_response(
    status: int, body: ErrorBody, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        body.model_dump(mode="json", exclude_none=True), status_code=status, headers=headers
    )


# Status codes FastAPI or Starlette raise themselves (unknown path, wrong
# method, and any HTTPException left in a dependency).
_CODE_FOR_STATUS = {
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    413: ErrorCode.PAYLOAD_TOO_LARGE,
    503: ErrorCode.UNAVAILABLE,
}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError) -> JSONResponse:
        return error_response(error.status, error.body, error.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        # FastAPI's field errors folded into one readable line, e.g.
        # "header.idempotency-key: Field required; query.limit: ...".
        detail = "; ".join(
            f"{'.'.join(str(part) for part in e['loc'])}: {e['msg']}" for e in error.errors()
        )
        return error_response(422, ErrorBody(code=ErrorCode.VALIDATION_FAILED, detail=detail))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        code = _CODE_FOR_STATUS.get(error.status_code)
        if code is None:
            raise RuntimeError(f"no ErrorCode for status {error.status_code}") from error
        return error_response(
            error.status_code, ErrorBody(code=code, detail=str(error.detail)), error.headers
        )


def errors(declared: dict[int, list[ErrorCode]]) -> dict:
    """The responses= of a route: for each error status it can send, the
    ErrorBody model and the codes it sends with that status, listed in the
    contract as x-error-codes. Declaring 422 also replaces FastAPI's own 422
    schema, which the validation handler above no longer sends."""
    return {
        status: {
            "model": ErrorBody,
            "description": f"{HTTPStatus(status).phrase}: " + ", ".join(codes),
            "x-error-codes": [str(c) for c in codes],
        }
        for status, codes in declared.items()
    }
