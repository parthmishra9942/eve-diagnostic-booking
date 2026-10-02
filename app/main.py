import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1 import api_router
from app.core.cache import cache
from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.core.exceptions import (
    AppError,
    app_error_handler,
    error_response,
    rate_limit_handler,
    validation_error_handler,
)
from app.core.logging import configure_logging, request_id_ctx
from app.core.rate_limit import limiter
from app.models import UserRole
from app.services.auth_service import AuthService

logger = logging.getLogger("app.request")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id and emits one structured access-log line per request."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        started = time.perf_counter()
        status_code = 500
        try:
            try:
                response = await call_next(request)
            except Exception:  # noqa: BLE001 - last-resort handler, never leak internals
                logger.exception("unhandled error")
                response = error_response(500, "internal_error", "Internal server error")
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            route = request.scope.get("route")
            logger.info(
                "request completed",
                extra={
                    "method": request.method,
                    "endpoint": getattr(route, "path", request.url.path),
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            request_id_ctx.reset(token)


async def _bootstrap_admin() -> None:
    if not (settings.admin_email and settings.admin_password):
        return
    try:
        async with SessionLocal() as session:
            await AuthService(session).create_user(
                email=settings.admin_email,
                full_name="Administrator",
                password=settings.admin_password,
                role=UserRole.ADMIN,
            )
        logging.getLogger(__name__).info("bootstrap admin created", extra={"email": settings.admin_email})
    except AppError:
        pass  # already exists
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("could not bootstrap admin user")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await _bootstrap_admin()
    yield
    await cache.close()
    await engine.dispose()


def create_app() -> FastAPI:
    configure_logging(settings.log_level)
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Diagnostic test bookings with simulated payments and an idempotent payment webhook.",
        lifespan=lifespan,
    )
    app.state.limiter = limiter
    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.include_router(api_router)

    @app.get("/health", tags=["Health"])
    async def health():
        """Liveness + dependency status. Redis being down is reported but does not fail the check."""
        db_ok = True
        try:
            async with SessionLocal() as session:
                await session.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001
            db_ok = False
        redis_ok = await cache.ping()
        body = {"status": "ok" if db_ok else "degraded", "database": db_ok, "cache": redis_ok}
        return body if db_ok else error_response(503, "unhealthy", "Database unreachable", body)

    return app


app = create_app()
