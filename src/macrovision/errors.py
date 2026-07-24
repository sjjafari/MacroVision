from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from macrovision.integrity import IntegrityConflictError


def _code(status_code: int) -> str:
    return {
        404: "resource_not_found",
        409: "conflict",
        422: "validation_error",
    }.get(status_code, "request_error")


async def http_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, HTTPException):
        raise exc
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": _code(exc.status_code),
            "message": message,
            "details": None,
            "detail": message,
        },
    )


async def validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    details: list[dict[str, Any]] = []
    for error in exc.errors()[:50]:
        details.append(
            {
                "location": [str(item) for item in error.get("loc", ())],
                "message": str(error.get("msg", "Invalid value"))[:500],
                "type": str(error.get("type", "value_error")),
            }
        )
    return JSONResponse(
        status_code=422,
        content={
            "code": "validation_error",
            "message": "Request validation failed",
            "details": details,
            "detail": details,
        },
    )


async def integrity_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, IntegrityConflictError):
        raise exc
    message = str(exc)
    return JSONResponse(
        status_code=409,
        content={
            "code": "conflict",
            "message": message,
            "details": None,
            "detail": message,
        },
    )
