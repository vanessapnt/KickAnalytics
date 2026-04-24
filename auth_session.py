import base64
import hashlib
import hmac
import json
import os
import time

from config import IS_PROD

# When I create an account or log in, the server sends back a payload and its signature,
# which are stored together as a cookie.
# On every subsequent request, the server verifies the cookie
# by recomputing the signature from the payload and comparing it to the stored signature in the cookie.

COOKIE_NAME = "ka_session"
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", "604800"))  # 7 days
SESSION_SECRET = _load_session_secret()

def _load_session_secret() -> str:
    secret = os.environ.get("SESSION_SECRET", "").strip()
    if secret:
        return secret

    # if no secret is set, use a default one in non-production environments, but raise an error in production
    if IS_PROD:
        raise RuntimeError("SESSION_SECRET is required in production")
    return "dev-change-me-session-secret"

# cookie only stores text, char like  {, ", :, espaces are not allowed, so we encode the payload and signature using base64url encoding (num, letters, - and _ only)
def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")

def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)

def _sign(payload_b64: str) -> str:
    mac = hmac.new(SESSION_SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
    return _b64url_encode(mac)

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
        if not hmac.compare_digest(sig_b64, _sign(payload_b64)):
            return None
        payload = json.loads(_b64url_decode(payload_b64).decode())
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload # success
    except Exception:
        return None

def set_session_cookie(response, token: str, *, secure: bool): # local -> requesrt.scheme = "http" -> secure = False
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True, # cookie is not accessible via JavaScript, helps prevent XSS attacks
        secure=secure, # cookie only sent over HTTPS, HTTP blocked, cookie can't be intercepted bc HTTPS is encrypted
        samesite="Lax", # cookie sent if we click a link to our site from another site, but not sent on cross-site requests, helps prevent CSRF attacks
        path="/", # cookie sent to all the routes
    )

def clear_session_cookie(response, *, secure: bool):
    response.del_cookie(COOKIE_NAME, path="/", secure=secure, httponly=True, samesite="Lax")

def get_session_user_from_request(request): # returns payload
    token = request.cookies.get(COOKIE_NAME)
    return verify_session_token(token)
