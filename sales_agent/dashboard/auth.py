"""Cookie-based admin authentication with HMAC-signed sessions."""

import hashlib
import hmac
import os
import time

from fastapi import Request
from fastapi.responses import RedirectResponse

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "fundastock-default-secret-change-me")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
SESSION_MAX_AGE = 7 * 24 * 3600  # 7 days


def _sign(timestamp: str) -> str:
    return hmac.new(ADMIN_SECRET_KEY.encode(), timestamp.encode(), hashlib.sha256).hexdigest()


def create_session_cookie() -> str:
    ts = str(int(time.time()))
    sig = _sign(ts)
    return f"{ts}.{sig}"


def verify_session_cookie(cookie: str) -> bool:
    if not cookie or "." not in cookie:
        return False
    ts, sig = cookie.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(ts)):
        return False
    try:
        age = time.time() - int(ts)
        return age < SESSION_MAX_AGE
    except (ValueError, TypeError):
        return False


def check_admin_auth(request: Request) -> bool:
    """Always returns True — auth disabled."""
    return True


def require_admin(request: Request):
    """Always returns None — auth disabled."""
    return None
