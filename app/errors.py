"""Every non-2xx response is an `ErrorOut`: a stable code the frontend handles by name, a fixed
message that never echoes the request, and the request id. Handlers raise `ApiError`; the app's
exception handlers (app/server.py) turn it, validation errors and unexpected exceptions into the
same body, so no traceback, secret or submitted text ever reaches the client."""

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        super().__init__(code)
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}


def request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def error_response(status: int, code: str, message: str, request_id: str | None = None,
                   headers: dict | None = None) -> JSONResponse:
    body = {"code": code, "message": message, "request_id": request_id}
    return JSONResponse(body, status_code=status, headers=headers or None)


def unauthenticated(message: str = "Sign in to continue.") -> ApiError:
    return ApiError(401, "unauthenticated", message, {"WWW-Authenticate": "Bearer"})


def forbidden(message: str = "You don't have access to this.") -> ApiError:
    return ApiError(403, "forbidden", message)


def not_found(message: str = "Not found.") -> ApiError:
    return ApiError(404, "not_found", message)
