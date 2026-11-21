"""The app factory's cross-cutting behaviour: ErrorOut on every failure, request ids, body limits,
security headers, CORS, health, the SPA fallback that never shadows /api or /health, and the
OpenAPI export."""

import json
from pathlib import Path
import os

import pytest

from app.server import create_app
from fakes_api import build_app, build_deps, client, make_user, login


@pytest.fixture
def http(tmp_path):
    app, deps = build_app(tmp_path)
    with client(app) as c:
        c.deps = deps
        yield c


def test_every_response_has_a_request_id_and_security_headers(http):
    r = http.get("/health/live")
    assert r.status_code == 200 and r.json() == {"alive": True}
    assert len(r.headers["x-request-id"]) == 36
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    err = http.get("/api/v1/auth/me")
    assert err.json()["request_id"] == err.headers["x-request-id"]


def test_errors_are_error_out_with_known_codes(http):
    missing = http.get("/api/v1/nope")
    assert missing.status_code == 404 and set(missing.json()) == {"code", "message", "request_id"}
    assert missing.json()["code"] == "not_found"
    wrong_method = http.delete("/api/v1/auth/login")
    assert wrong_method.status_code == 405 and wrong_method.json()["code"] == "not_found"
    bad_json = http.post("/api/v1/auth/login", content=b"{not json", headers={"content-type": "application/json"})
    assert bad_json.status_code == 422 and bad_json.json()["code"] == "validation_error"


def test_validation_errors_name_fields_only_and_never_echo_input(http):
    r = http.post("/api/v1/auth/login", json={"email": "jane.roe@example.com"})
    assert r.status_code == 422 and r.json() == {"code": "validation_error",
                                                 "message": "Check the request fields: password.",
                                                 "request_id": r.headers["x-request-id"]}
    assert "jane" not in r.text.lower()


def test_oversized_json_bodies_are_refused_before_parsing(http):
    make_user(http.deps, "s@example.com")
    headers = login(http, "s@example.com")
    body = json.dumps({"question": "patient Jane Roe " * 2000})
    r = http.post("/api/v1/ask", content=body, headers={**headers, "content-type": "application/json"})
    assert r.status_code == 413 and r.json()["code"] == "too_large" and "Jane" not in r.text


def test_unexpected_exceptions_become_a_fixed_500(tmp_path, caplog):
    deps = build_deps(tmp_path)
    deps.store.users.by_email_for_login = lambda email: 1 / 0
    with client(create_app(deps), raise_server_exceptions=False) as http:
        r = http.post("/api/v1/auth/login", json={"email": "a@b.co", "password": "whatever123"})
    assert r.status_code == 500 and r.json()["code"] == "server_error"
    assert "ZeroDivision" not in r.text and "Traceback" not in r.text


def test_readiness_reports_each_check(http):
    r = http.get("/health/ready")
    assert r.status_code == 200
    assert r.json() == {"ready": True, "checks": {"postgres": True, "cache": True, "storage": True, "llm_config": True},
                        "version": "2.0.0", "generation": 1}
    http.deps.cache.alive = False
    r = http.get("/health/ready")
    assert r.status_code == 503 and r.json()["ready"] is False and r.json()["checks"]["cache"] is False
    http.deps.cache.alive, http.deps.store.alive = True, False
    assert http.get("/health/ready").json()["checks"]["postgres"] is False


def test_the_store_is_closed_on_shutdown(tmp_path):
    app, deps = build_app(tmp_path)
    with client(app):
        pass
    assert deps.store.closed is True


def test_without_a_frontend_build_the_root_says_so(http):
    r = http.get("/")
    assert r.status_code == 200 and "not built" in r.json()["frontend"]


def test_spa_fallback_serves_the_build_but_never_api_or_health(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>PharmAssist</title>")
    (dist / "assets" / "app-abc.js").write_text("console.log(1)")
    (dist / "favicon.svg").write_text("<svg/>")
    app, deps = build_app(tmp_path, frontend_dir=dist)
    with client(app) as http:
        for path in ("/", "/ask", "/admin/users/42", "/some/deep/link"):
            r = http.get(path)
            assert r.status_code == 200 and "PharmAssist" in r.text and r.headers["cache-control"] == "no-cache", path
        assert http.get("/assets/app-abc.js").text == "console.log(1)"
        assert http.get("/favicon.svg").text == "<svg/>"
        for path in ("/api/v1/nothing", "/api/v1", "/api", "/health/nothing", "/health"):
            r = http.get(path)
            assert r.status_code == 404 and r.json()["code"] == "not_found", path
        assert http.get("/health/live").json() == {"alive": True}
        assert http.get("/api/v1/auth/me").status_code == 401
        assert http.get("/../etc/passwd").status_code in (200, 404)   # normalised: never a file outside dist
        assert "root:" not in http.get("/../etc/passwd").text


def test_cors_only_for_the_configured_origins(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_CORS_ORIGINS", "http://localhost:5173")
    app, _ = build_app(tmp_path)
    with client(app) as http:
        ok = http.options("/api/v1/auth/login", headers={"Origin": "http://localhost:5173",
                                                         "Access-Control-Request-Method": "POST"})
        assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert ok.headers["access-control-allow-credentials"] == "true"
        other = http.options("/api/v1/auth/login", headers={"Origin": "https://evil.example",
                                                            "Access-Control-Request-Method": "POST"})
        assert "access-control-allow-origin" not in other.headers
    monkeypatch.delenv("APP_CORS_ORIGINS")
    app, _ = build_app(tmp_path)
    with client(app) as http:
        r = http.get("/health/live", headers={"Origin": "http://localhost:5173"})
        assert "access-control-allow-origin" not in r.headers


def test_openapi_lists_every_v1_route_with_error_out(tmp_path):
    app, _ = build_app(tmp_path)
    spec = app.openapi()
    paths = set(spec["paths"])
    for p in ("/api/v1/auth/signup", "/api/v1/auth/login", "/api/v1/auth/refresh", "/api/v1/auth/logout",
              "/api/v1/auth/me", "/api/v1/ask", "/api/v1/conversations", "/api/v1/conversations/{conversation_id}",
              "/api/v1/messages/{message_id}/feedback", "/api/v1/sources/{doc_id}/{name}",
              "/api/v1/figures/{doc_id}/{name}", "/api/v1/admin/stats", "/api/v1/admin/conversations",
              "/api/v1/admin/messages/{message_id}", "/api/v1/admin/documents",
              "/api/v1/admin/documents/{doc_id}/reindex", "/api/v1/admin/jobs", "/api/v1/admin/users",
              "/api/v1/admin/users/{user_id}", "/api/v1/admin/cache/stats", "/api/v1/admin/cache", "/health/ready"):
        assert p in paths, p
    assert "AnswerOut" in spec["components"]["schemas"] and "ErrorOut" in spec["components"]["schemas"]
    assert os.environ.get("APP_OPENAPI") != "1" and app.openapi_url is None   # not served unless asked


def test_export_openapi_writes_the_frontend_document(tmp_path):
    import importlib.util
    spec_path = Path(__file__).resolve().parents[1] / "scripts" / "export_openapi.py"
    module = importlib.util.module_from_spec(s := importlib.util.spec_from_file_location("export_openapi", spec_path))
    s.loader.exec_module(module)
    out = tmp_path / "frontend" / "openapi.json"
    assert module.main(["--out", str(out)]) == 0
    spec = json.loads(out.read_text())
    assert "/api/v1/ask" in spec["paths"] and spec["components"]["schemas"]["AnswerOut"]["properties"]["cached"]
    assert spec["paths"]["/api/v1/ask"]["post"]["responses"]["4XX"]["content"]["application/json"]["schema"]["$ref"].endswith("ErrorOut")
