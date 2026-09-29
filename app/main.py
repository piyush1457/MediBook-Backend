"""App factory, routers, uniform error shape, logging middleware."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routers import auth, bookings, centres, payments, tests
from app.core.config import settings
from app.core.errors import DomainError
from app.core.logging import RequestIdMiddleware, setup_logging


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


def create_app() -> FastAPI:
    setup_logging(settings.LOG_LEVEL)
    app = FastAPI(title=settings.APP_NAME, version="1.0.0")
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(DomainError)
    async def domain_handler(_: Request, exc: DomainError) -> JSONResponse:
        return _error(exc.code, exc.message, exc.http_status)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error(
            "validation_error", str(exc.errors()[0].get("msg", "Invalid request")), 422
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        return _error(code, str(exc.detail), exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled_handler(_: Request, exc: Exception) -> JSONResponse:  # noqa: BLE001
        return _error("internal_error", "Internal server error", 500)

    @app.get("/health", tags=["ops"], summary="Health check")
    def health() -> dict:
        return {"status": "ok"}

    prefix = settings.API_PREFIX
    app.include_router(auth.router, prefix=prefix)
    app.include_router(centres.router, prefix=prefix)
    app.include_router(tests.router, prefix=prefix)
    app.include_router(bookings.router, prefix=prefix)
    app.include_router(payments.router, prefix=prefix)
    return app


app = create_app()
