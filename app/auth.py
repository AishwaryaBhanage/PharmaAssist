"""Authentication (config `auth:`): signup, login, refresh, logout, me, and the `current_user` /
`require_admin` dependencies every other router uses.

- Passwords are argon2id hashes; the plain text is never logged or stored.
- The access token is a short-lived HS256 JWT (`sub`, `role`, `exp`, `iat`, `jti`) sent as a Bearer
  header. Every request re-reads the user, so a deactivated account loses access at once.
- The refresh token is 256 random bits, stored as its sha256 in `store.tokens` and sent only as the
  `pa_refresh` HttpOnly cookie scoped to `/api/v1/auth`. `/refresh` rotates it: the old token is
  marked replaced, and presenting a replaced token again (a stolen copy) revokes the user's whole
  chain. `Secure` is dropped only when APP_INSECURE_COOKIES=1 (plain-http local development).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Depends, Request, Response

from app.api.schemas import LoginIn, SignupIn, TokenOut, UserOut
from app.deps import API, Deps, get_deps
from app.errors import ApiError, forbidden, unauthenticated
from app.views import user_out
from pharmassist.store.protocols import Conflict, User

log = logging.getLogger("pharmassist.app")
router = APIRouter(prefix=f"{API}/auth", tags=["auth"])
_hasher = PasswordHasher()
COOKIE_PATH = f"{API}/auth"
LEEWAY_S = 5


# ---------------------------------------------------------------- passwords and tokens

def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, ValueError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def make_access_token(user: User, deps: Deps) -> tuple[str, int]:
    minutes = int(deps.auth_cfg.get("access_token_minutes", 15))
    now = deps.clock()
    claims = {"sub": user.id, "role": user.role, "iat": int(now.timestamp()),
              "exp": int((now + timedelta(minutes=minutes)).timestamp()), "jti": uuid.uuid4().hex}
    return jwt.encode(claims, deps.jwt_secret, algorithm="HS256"), minutes * 60


def decode_access_token(token: str, deps: Deps) -> dict:
    """Signature and claims via PyJWT; `exp`/`iat` against the app's clock (injectable in tests)."""
    try:
        claims = jwt.decode(token, deps.jwt_secret, algorithms=["HS256"],
                            options={"require": ["exp", "sub", "iat", "jti"], "verify_exp": False, "verify_iat": False})
    except jwt.InvalidTokenError:
        raise unauthenticated("Invalid access token.")
    now = deps.clock().timestamp()
    if not isinstance(claims["exp"], (int, float)) or not isinstance(claims["iat"], (int, float)):
        raise unauthenticated("Invalid access token.")
    if claims["exp"] <= now - LEEWAY_S:
        raise ApiError(401, "token_expired", "Your session has expired. Refresh and try again.",
                       {"WWW-Authenticate": "Bearer"})
    if claims["iat"] > now + LEEWAY_S:
        raise unauthenticated("Invalid access token.")
    return claims


def issue_refresh(user: User, deps: Deps, response: Response, *, rotate_from: str | None = None) -> None:
    days = int(deps.auth_cfg.get("refresh_token_days", 14))
    token = secrets.token_urlsafe(32)              # 256 bits
    expires = deps.clock() + timedelta(days=days)
    if rotate_from:
        deps.store.tokens.rotate(rotate_from, token_hash(token), expires)
    else:
        deps.store.tokens.issue(user.id, token_hash(token), expires)
    response.set_cookie(cookie_name(deps), token, max_age=days * 86400, path=COOKIE_PATH, httponly=True,
                        secure=not deps.insecure_cookies, samesite="lax")


def cookie_name(deps: Deps) -> str:
    return deps.auth_cfg.get("refresh_cookie", "pa_refresh")


def clear_refresh(deps: Deps, response: Response) -> None:
    response.delete_cookie(cookie_name(deps), path=COOKIE_PATH, httponly=True, secure=not deps.insecure_cookies,
                           samesite="lax")


def _session_error(deps: Deps, message: str, status: int = 401, code: str = "unauthenticated") -> ApiError:
    """An auth failure that also clears the refresh cookie: error responses are built by the exception
    handler, so the cookie header has to travel with the error."""
    resp = Response()
    clear_refresh(deps, resp)
    headers = {"Set-Cookie": resp.headers["set-cookie"]}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return ApiError(status, code, message, headers)


def token_response(user: User, deps: Deps) -> TokenOut:
    access, expires_in = make_access_token(user, deps)
    return TokenOut(access_token=access, expires_in=expires_in, user=user_out(user))


# ---------------------------------------------------------------- dependencies

def bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def user_from_token(token: str | None, deps: Deps) -> User:
    if not token:
        raise unauthenticated()
    claims = decode_access_token(token, deps)
    user = deps.store.users.by_id(str(claims.get("sub")))
    if user is None:
        raise unauthenticated("This account no longer exists.")
    if not user.is_active:
        raise forbidden("This account is deactivated.")
    return user


def current_user(request: Request, deps: Deps = Depends(get_deps)) -> User:
    return user_from_token(bearer_token(request), deps)


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise forbidden("Administrator access is required.")
    return user


# ---------------------------------------------------------------- routes

@router.post("/signup", response_model=TokenOut, status_code=201)
def signup(body: SignupIn, response: Response, deps: Deps = Depends(get_deps)):
    cfg = deps.auth_cfg
    if not cfg.get("signup_enabled", True):
        raise ApiError(403, "signup_disabled", "Sign-up is disabled. Ask an administrator for an account.")
    if len(body.password) < int(cfg.get("password_min_chars", 10)):
        raise ApiError(422, "weak_password", f"Use at least {cfg.get('password_min_chars', 10)} characters.")
    try:
        user = deps.store.users.create(body.email.lower(), hash_password(body.password),
                                       cfg.get("default_role", "staff"), body.display_name.strip())
    except Conflict:
        raise ApiError(409, "email_taken", "An account with this email already exists.")
    deps.store.users.touch_login(user.id)
    issue_refresh(user, deps, response)
    log.info("signup %s role=%s", user.id, user.role)
    return token_response(user, deps)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, response: Response, deps: Deps = Depends(get_deps)):
    user = deps.store.users.by_email_for_login(body.email.lower())
    if user is None or not verify_password(user.password_hash, body.password):
        raise ApiError(401, "invalid_credentials", "Email or password is incorrect.")
    if not user.is_active:
        raise forbidden("This account is deactivated.")
    deps.store.users.touch_login(user.id)
    user = deps.store.users.by_id(user.id) or user
    issue_refresh(user, deps, response)
    log.info("login %s", user.id)
    return token_response(user, deps)


@router.post("/refresh", response_model=TokenOut)
def refresh(request: Request, response: Response, deps: Deps = Depends(get_deps)):
    raw = request.cookies.get(cookie_name(deps))
    if not raw:
        raise unauthenticated("No session. Sign in again.")
    stored = deps.store.tokens.by_hash(token_hash(raw))
    if stored is None:
        raise _session_error(deps, "Session not recognised. Sign in again.")
    if stored.revoked_at is not None:
        # a replaced token presented again: someone holds a copy; end every session of this user
        deps.store.tokens.revoke_all(stored.user_id)
        log.warning("refresh token reuse for user %s: all sessions revoked", stored.user_id)
        raise _session_error(deps, "Session invalidated. Sign in again.")
    if stored.expires_at <= deps.clock():
        deps.store.tokens.revoke(stored.id)
        raise _session_error(deps, "Session expired. Sign in again.")
    user = deps.store.users.by_id(stored.user_id)
    if user is None or not user.is_active:
        deps.store.tokens.revoke_all(stored.user_id)
        raise _session_error(deps, "This account is deactivated.", 403, "forbidden")
    issue_refresh(user, deps, response, rotate_from=stored.id)
    return token_response(user, deps)


@router.post("/logout", status_code=204, response_class=Response)
def logout(request: Request, response: Response, deps: Deps = Depends(get_deps)):
    raw = request.cookies.get(cookie_name(deps))
    if raw:
        stored = deps.store.tokens.by_hash(token_hash(raw))
        if stored is not None:
            deps.store.tokens.revoke(stored.id)
    clear_refresh(deps, response)
    return Response(status_code=204, headers=dict(response.headers))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user_out(user)
