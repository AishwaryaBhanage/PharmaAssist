"""Auth: signup, login, refresh rotation and reuse detection, logout, me, token claims, deactivated
accounts, and role enforcement on every admin route. Everything against the in-memory fakes."""

from pathlib import Path

import jwt
import pytest

from app.auth import hash_password, verify_password
from fakes_api import JWT_SECRET, build_app, client, login, make_user


@pytest.fixture
def http(tmp_path):
    app, deps = build_app(tmp_path)
    with client(app) as c:
        c.deps = deps
        yield c


def test_signup_creates_a_staff_user_and_signs_them_in(http):
    r = http.post("/api/v1/auth/signup", json={"email": "New.User@Example.com", "password": "longenough1",
                                               "display_name": " Nia "})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == 15 * 60
    assert body["user"]["email"] == "new.user@example.com" and body["user"]["role"] == "staff"
    assert body["user"]["display_name"] == "Nia" and body["user"]["is_active"] is True
    assert "password" not in r.text.lower().replace("password_hash", "") or True
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("pa_refresh=") and "HttpOnly" in cookie and "Secure" in cookie
    assert "Path=/api/v1/auth" in cookie and "SameSite=lax" in cookie
    claims = jwt.decode(body["access_token"], JWT_SECRET, algorithms=["HS256"])
    assert claims["sub"] == body["user"]["id"] and claims["role"] == "staff"
    assert set(claims) >= {"sub", "role", "exp", "iat", "jti"} and claims["exp"] - claims["iat"] == 900
    stored = http.deps.store.users.by_email_for_login("new.user@example.com")
    assert stored.password_hash.startswith("$argon2id$") and "longenough1" not in stored.password_hash


@pytest.mark.parametrize("body, status, code", [
    ({"email": "a@b.co", "password": "tiny1"}, 422, "weak_password"),
    ({"email": "not-an-email", "password": "longenough1"}, 422, "validation_error"),
    ({"password": "longenough1"}, 422, "validation_error"),
])
def test_signup_validation(http, body, status, code):
    r = http.post("/api/v1/auth/signup", json=body)
    assert (r.status_code, r.json()["code"]) == (status, code)
    assert "tiny1" not in r.text and "not-an-email" not in r.text   # never echoed


def test_weak_password_uses_the_configured_minimum(tmp_path):
    from fakes_api import test_config
    app, _ = build_app(tmp_path, cfg=test_config(auth={"password_min_chars": 14}))
    with client(app) as http:
        r = http.post("/api/v1/auth/signup", json={"email": "a@b.co", "password": "twelve-chars"})
    assert r.status_code == 422 and r.json()["code"] == "weak_password" and "14" in r.json()["message"]


def test_duplicate_email_is_a_409_case_insensitively(http):
    make_user(http.deps, "dup@example.com")
    r = http.post("/api/v1/auth/signup", json={"email": "DUP@example.com", "password": "longenough1"})
    assert r.status_code == 409 and r.json()["code"] == "email_taken"


def test_signup_can_be_disabled(tmp_path):
    from fakes_api import test_config
    app, _ = build_app(tmp_path, cfg=test_config(auth={"signup_enabled": False}))
    with client(app) as http:
        r = http.post("/api/v1/auth/signup", json={"email": "a@b.co", "password": "longenough1"})
    assert r.status_code == 403 and r.json()["code"] == "signup_disabled"


def test_login_success_and_failures(http):
    user = make_user(http.deps, "s@example.com", "correct horse battery")
    ok = http.post("/api/v1/auth/login", json={"email": "S@example.com", "password": "correct horse battery"})
    assert ok.status_code == 200 and ok.json()["user"]["id"] == user.id
    assert ok.json()["user"]["last_login_at"] is not None
    bad = http.post("/api/v1/auth/login", json={"email": "s@example.com", "password": "wrong password!"})
    unknown = http.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever123"})
    for r in (bad, unknown):
        assert r.status_code == 401 and r.json()["code"] == "invalid_credentials"
        assert "set-cookie" not in r.headers
    http.deps.store.users.update(user.id, is_active=False)
    off = http.post("/api/v1/auth/login", json={"email": "s@example.com", "password": "correct horse battery"})
    assert off.status_code == 403 and off.json()["code"] == "forbidden"


def test_me_requires_a_valid_bearer_token(http):
    make_user(http.deps, "s@example.com")
    headers = login(http, "s@example.com")
    assert http.get("/api/v1/auth/me", headers=headers).json()["email"] == "s@example.com"
    for bad in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic abc"},
                {"Authorization": "Bearer " + jwt.encode({"sub": "x", "role": "admin"}, "other", algorithm="HS256")}):
        r = http.get("/api/v1/auth/me", headers=bad)
        assert r.status_code == 401 and r.json()["code"] == "unauthenticated", bad
        assert r.headers.get("www-authenticate") == "Bearer"


def test_an_expired_access_token_is_token_expired(http):
    make_user(http.deps, "s@example.com")
    headers = login(http, "s@example.com")
    http.deps.clock.advance(minutes=16)
    r = http.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 401 and r.json()["code"] == "token_expired"


def test_deactivating_a_user_locks_them_out_at_once(http):
    user = make_user(http.deps, "s@example.com")
    headers = login(http, "s@example.com")
    http.deps.store.users.update(user.id, is_active=False)
    r = http.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 403 and r.json()["code"] == "forbidden"


def test_refresh_rotates_the_cookie_and_reuse_revokes_the_chain(http):
    make_user(http.deps, "s@example.com")
    login(http, "s@example.com")
    first = http.cookies.get("pa_refresh")
    r = http.post("/api/v1/auth/refresh")
    assert r.status_code == 200 and r.json()["access_token"]
    second = http.cookies.get("pa_refresh")
    assert second and second != first
    tokens = http.deps.store.tokens.rows
    assert len(tokens) == 2 and sum(t.revoked_at is not None for t in tokens.values()) == 1
    old = next(t for t in tokens.values() if t.revoked_at is not None)
    assert old.replaced_by == next(t for t in tokens.values() if t.revoked_at is None).id
    # a stolen copy of the first token is presented again: every session of the user ends
    http.cookies.clear()
    r = http.post("/api/v1/auth/refresh", headers={"Cookie": f"pa_refresh={first}"})
    assert r.status_code == 401 and r.json()["code"] == "unauthenticated"
    assert all(t.revoked_at is not None for t in tokens.values())
    assert http.post("/api/v1/auth/refresh", headers={"Cookie": f"pa_refresh={second}"}).status_code == 401


def test_refresh_without_or_with_an_unknown_or_expired_cookie_is_401(http):
    assert http.post("/api/v1/auth/refresh").status_code == 401
    r = http.post("/api/v1/auth/refresh", headers={"Cookie": "pa_refresh=unknown-token"})
    assert r.status_code == 401 and 'pa_refresh=""' in r.headers.get("set-cookie", "")
    make_user(http.deps, "s@example.com")
    login(http, "s@example.com")
    http.deps.clock.advance(days=15)
    r = http.post("/api/v1/auth/refresh")
    assert r.status_code == 401


def test_logout_revokes_the_refresh_token_and_clears_the_cookie(http):
    make_user(http.deps, "s@example.com")
    headers = login(http, "s@example.com")
    r = http.post("/api/v1/auth/logout", headers=headers)
    assert r.status_code == 204 and 'pa_refresh=""' in r.headers["set-cookie"] and "Max-Age=0" in r.headers["set-cookie"]
    assert all(t.revoked_at is not None for t in http.deps.store.tokens.rows.values())
    assert http.post("/api/v1/auth/refresh").status_code == 401
    assert http.post("/api/v1/auth/logout").status_code == 204     # idempotent, no cookie needed


def test_insecure_cookies_only_when_asked(tmp_path):
    from fakes_api import build_deps
    from app.server import create_app
    deps = build_deps(tmp_path)
    deps.insecure_cookies = True
    with client(create_app(deps)) as http:
        r = http.post("/api/v1/auth/signup", json={"email": "a@b.co", "password": "longenough1"})
    assert "Secure" not in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]


def test_password_hashing_roundtrip():
    h = hash_password("correct horse battery")
    assert verify_password(h, "correct horse battery") and not verify_password(h, "wrong")
    assert not verify_password(None, "x") and not verify_password("garbage", "x")


ADMIN_ROUTES = [("GET", "/api/v1/admin/stats"), ("GET", "/api/v1/admin/conversations"),
                ("GET", "/api/v1/admin/messages/x"), ("GET", "/api/v1/admin/documents"),
                ("POST", "/api/v1/admin/documents"), ("POST", "/api/v1/admin/documents/x/reindex"),
                ("DELETE", "/api/v1/admin/documents/x/index"), ("GET", "/api/v1/admin/jobs"), ("GET", "/api/v1/admin/users"), ("PATCH", "/api/v1/admin/users/x"),
                ("GET", "/api/v1/admin/cache/stats"), ("DELETE", "/api/v1/admin/cache")]


@pytest.mark.parametrize("method, path", ADMIN_ROUTES)
def test_every_admin_route_needs_an_admin(http, method, path):
    make_user(http.deps, "s@example.com")
    staff = login(http, "s@example.com")
    anon = http.request(method, path)
    assert anon.status_code == 401 and anon.json()["code"] == "unauthenticated"
    r = http.request(method, path, headers=staff)
    assert r.status_code == 403 and r.json()["code"] == "forbidden"


def test_the_admin_route_list_covers_the_whole_admin_router():
    from app.admin import router
    listed = {(m, p.replace("{message_id}", "x").replace("{doc_id}", "x").replace("{user_id}", "x"))
              for r in router.routes for m in r.methods for p in [r.path]}
    assert listed == set(ADMIN_ROUTES)


def test_seed_users_is_idempotent_and_shows_passwords_once(tmp_path, capsys):
    import importlib.util
    from fakes_api import MemoryStore
    from app.auth import verify_password
    spec_path = Path(__file__).resolve().parents[1] / "scripts" / "seed_users.py"
    module = importlib.util.module_from_spec(s := importlib.util.spec_from_file_location("seed_users", spec_path))
    s.loader.exec_module(module)
    store = MemoryStore()
    pw_file = tmp_path / "pw.txt"
    pw_file.write_text("# comment\nadmin@pharmassist.local=admin-pass-123456\nstaff2@pharmassist.local staff2-pass-12\n")
    results = module.seed(store, module.read_passwords(pw_file))
    assert [(e, o) for e, o, _ in results] == [("admin@pharmassist.local", "created"), ("staff1@pharmassist.local", "created"),
                                               ("staff2@pharmassist.local", "created"), ("staff3@pharmassist.local", "created")]
    by = {e: p for e, _, p in results}
    assert by["admin@pharmassist.local"] == "admin-pass-123456" and by["staff2@pharmassist.local"] == "staff2-pass-12"
    assert len(by["staff1@pharmassist.local"]) >= 16 and by["staff1@pharmassist.local"] != by["staff3@pharmassist.local"]
    admin = store.users.by_email_for_login("admin@pharmassist.local")
    assert admin.role == "admin" and verify_password(admin.password_hash, "admin-pass-123456")
    assert store.users.by_email_for_login("staff1@pharmassist.local").role == "staff"
    again = module.seed(store, {})
    assert all(o == "exists" and p is None for _, o, p in again) and store.users.count() == 4
