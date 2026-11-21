"""The PharmAssist API (v2): `create_app(deps)` assembles the routers under /api/v1, the health
checks and the React build, around the dependencies in `app.deps.Deps`.

Run locally: uvicorn app.main:app --port 8000   (from the repository root; app/main.py builds
the real dependencies from config.yaml and the environment).

Cross-cutting rules, all here:
- every response carries `X-Request-Id`; /ask uses the same id for the stored message and the trace;
- every non-2xx body is `ErrorOut` (app/api/schemas.py); validation errors name the fields only, so
  the submitted text is never echoed; unexpected exceptions become a fixed 500;
- JSON bodies are capped at app.max_body_bytes (uploads at uploads.max_bytes);
- security headers on every response; CORS only for the origins in APP_CORS_ORIGINS (the Vite dev
  server); the SPA in frontend/dist is served with a fallback for non-API paths, and /api/* and
  /health/* are never shadowed by it;
- readiness checks the store and the cache; with APP_WARM_MODELS=1 (the Docker image) startup also
  loads the reranker config.yaml search.rerank names, so the first search doesn't pay for it.
Logs carry request ids and outcomes, never a question, an answer or a secret.
"""

from __future__ import annotations

import logging
import anyio
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import admin, ask, auth, feedback, sources
from app.api import schemas as S
from app.deps import API, Deps
from app.errors import ApiError, error_response, request_id_of

log = logging.getLogger("pharmassist.app")
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                               "img-src 'self' data: blob: https:; connect-src 'self' https:; frame-ancestors 'none'; "
                               "base-uri 'none'; form-action 'self'; object-src 'none'",
    "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
UPLOAD_PATH = f"{API}/admin/documents"
# a pydantic error on these fields has a code of its own (schemas.py), so the frontend can name it
FIELD_CODES = {("password", "string_too_short"): (422, "weak_password", "The password is too short."),
               ("question", "string_too_short"): (422, "question_too_short", "Enter a question."),
               ("question", "string_too_long"): (422, "question_too_long", "The question is too long.")}
HTTP_CODES = {401: "unauthenticated", 403: "forbidden", 404: "not_found", 405: "not_found", 413: "too_large",
              422: "validation_error"}


def create_app(deps: Deps) -> FastAPI:
    max_body = int(deps.app_cfg.get("max_body_bytes", 16_384))
    max_upload = int((deps.cfg.get("uploads") or {}).get("max_bytes", 50 * 1024 * 1024)) + 1024 * 1024
    cors_origins = [o.strip() for o in os.environ.get("APP_CORS_ORIGINS", "").split(",") if o.strip()]

    def readiness() -> dict:
        checks = {}
        for name, fn in (("postgres", deps.store.ping), ("cache", deps.cache.ping), ("storage", deps.storage.ping),
                         ("llm_config", deps.answers.configured)):
            try:
                checks[name] = bool(fn())
            except Exception as e:
                log.error("readiness %s: %s", name, type(e).__name__)
                checks[name] = False
        generation = None
        if checks["postgres"]:
            try:
                generation = deps.store.documents.generation()
            except Exception:
                checks["postgres"] = False
        return {"ready": all(checks.values()), "checks": checks, "version": deps.version or "2.0.0",
                "generation": generation}

    @asynccontextmanager
    async def lifespan(app):
        app.state.ready = readiness()
        log.info("startup: %s", ", ".join(f"{k}={'ok' if v else 'down'}" for k, v in app.state.ready["checks"].items()))
        if os.environ.get("APP_WARM_MODELS") == "1":
            try:
                from pharmassist.search.hybrid import warm as warm_search
                timings = await anyio.to_thread.run_sync(warm_search, deps.cfg.get("search"))
                log.info("startup: reranker %s", timings or "off")
            except Exception as e:       # the first search then loads it (or runs without it)
                log.error("startup: reranker warmup failed: %s", type(e).__name__)
        yield
        try:
            deps.store.close()
        except Exception as e:
            log.error("store close failed: %s", type(e).__name__)

    app = FastAPI(title="PharmAssist API", version=deps.version or "2.0.0", lifespan=lifespan, docs_url=None,
                  redoc_url=None, openapi_url=f"{API}/openapi.json" if os.environ.get("APP_OPENAPI") == "1" else None)
    app.state.deps = deps

    if cors_origins:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_credentials=True,
                           allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["*"],
                           expose_headers=["X-Request-Id", "Retry-After"])

    @app.middleware("http")
    async def envelope(request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        limit = max_upload if request.url.path == UPLOAD_PATH and request.method == "POST" else max_body
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > limit):
            resp = error_response(413, "too_large", "The request is too large.", request_id)
        else:
            resp = await call_next(request)
        resp.headers.update(SECURITY_HEADERS)
        resp.headers["X-Request-Id"] = request_id
        return resp

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return error_response(exc.status, exc.code, exc.message, request_id_of(request), exc.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        for e in errors:
            key = (str(e["loc"][-1]) if e.get("loc") else "", str(e.get("type", "")))
            if key in FIELD_CODES:
                status, code, message = FIELD_CODES[key]
                return error_response(status, code, message, request_id_of(request))
        fields = sorted({str(e["loc"][-1]) for e in errors if e.get("loc")})
        return error_response(422, "validation_error", "Check the request fields: " + ", ".join(fields) + ".",
                              request_id_of(request))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return error_response(exc.status_code, HTTP_CODES.get(exc.status_code, "server_error"), message,
                              request_id_of(request), getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        log.error("unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path)
        return error_response(500, "server_error", "Something went wrong. Please try again.", request_id_of(request))

    @app.get("/health/live", include_in_schema=False)
    def live():
        return {"alive": True}

    @app.get("/health/ready", response_model=S.HealthOut, responses={503: {"model": S.HealthOut}})
    def ready():
        out = readiness()
        app.state.ready = out
        return JSONResponse(S.HealthOut(**out).model_dump(), status_code=200 if out["ready"] else 503)

    for r in (auth.router, ask.router, feedback.router, sources.router, admin.router):
        app.include_router(r, responses={"4XX": {"model": S.ErrorOut}, "5XX": {"model": S.ErrorOut}})

    # ---- the React build ----
    dist = Path(deps.frontend_dir)
    index = dist / "index.html"
    if index.exists():
        if (dist / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path in ("api", "health") or path.startswith(("api/", "health/")):
                raise ApiError(404, "not_found", "No such endpoint.")
            candidate = (dist / path).resolve() if path else index
            if path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-cache"})
    else:
        @app.get("/", include_in_schema=False)
        def root():
            return {"name": "PharmAssist API", "api": API, "frontend": "not built (frontend/dist missing)"}

    return app
