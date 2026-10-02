from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.core.logging import request_id_ctx


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, headers: dict[str, str] | None = None):
        super().__init__(message)
        self.message = message
        self.headers = headers


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "error": {"code": code, "message": message, "request_id": request_id_ctx.get()}
    }
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body), headers=headers)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, headers=exc.headers)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = []
    for err in exc.errors():
        location = ".".join(str(part) for part in err["loc"] if part != "body")
        message = str(err["msg"]).removeprefix("Value error, ")
        details.append({"field": location, "message": message})
    summary = "; ".join(f"{d['field']}: {d['message']}" if d["field"] else d["message"] for d in details)
    return error_response(422, "validation_error", summary or "Request validation failed", details)


async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return error_response(429, "rate_limited", f"Rate limit exceeded: {exc.detail}")
