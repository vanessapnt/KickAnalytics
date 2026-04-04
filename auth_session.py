import base64
import hashlib
import hmac
import json
import os
import time

COOKIE_NAME = "ka_session"
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", "604800"))  # 7 days


def _load_session_secrets():
    raw_many = os.environ.get("SESSION_SECRETS", "").strip()
    if raw_many:
        return [s.strip() for s in raw_many.split(",") if s.strip()]

    raw_single = os.environ.get("SESSION_SECRET", "").strip()
    if raw_single:
        return [raw_single]

    env_name = os.environ.get("ENV", "development").strip().lower()
    if env_name in ("prod", "production"):
        raise RuntimeError("SESSION_SECRET or SESSION_SECRETS is required in production")

    return ["dev-change-me-session-secret"]


SESSION_SECRETS = _load_session_secrets()
ACTIVE_SESSION_SECRET = SESSION_SECRETS[0]


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _sign_with(secret: str, payload_b64: str) -> str:
    mac = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    return _b64url_encode(mac)


def _sign(payload_b64: str) -> str:
    return _sign_with(ACTIVE_SESSION_SECRET, payload_b64)


def create_session_token(*, user_id: str, username: str, display_name: str) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "username": username,
        "display_name": display_name,
        "iat": now,
        "exp": now + SESSION_TTL_SECONDS,
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    sig_b64 = _sign(payload_b64)
    return f"{payload_b64}.{sig_b64}"


def verify_session_token(token: str):
    if not token or "." not in token:
        return None
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        if not any(hmac.compare_digest(sig_b64, _sign_with(secret, payload_b64)) for secret in SESSION_SECRETS):
            return None
        payload = json.loads(_b64url_decode(payload_b64).decode())
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def set_session_cookie(response, token: str, *, secure: bool):
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=secure,
        samesite="Lax",
        path="/",
    )


def clear_session_cookie(response, *, secure: bool):
    response.del_cookie(COOKIE_NAME, path="/", secure=secure, httponly=True, samesite="Lax")


def get_session_user_from_request(request):
    token = request.cookies.get(COOKIE_NAME)
    return verify_session_token(token)
