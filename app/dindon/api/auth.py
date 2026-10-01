"""The one password that protects the interface, even for a single user.

A signed cookie: `<expiry>.<HMAC>`, with a key made from the password (changing the password signs everyone out).
HttpOnly, SameSite=Strict, and every write needs a JSON body, which a page of another site cannot send.
After a few wrong passwords, logging in is refused for a while.
"""
import hashlib
import hmac
import time

from fastapi import HTTPException, Request

COOKIE = "dindon_session"
LIFETIME = 7 * 24 * 3600
MAX_FAILURES = 5
LOCK_SECONDS = 30


class Auth:
    def __init__(self, password: str):
        if not password:
            raise RuntimeError("DINDON_PASSWORD is empty: choose a password in .env, the interface is never served without one")
        self._password = password.encode()
        self._key = hashlib.sha256(b"dindon-session|" + self._password).digest()
        self._failures: list[float] = []

    def check_password(self, candidate: str) -> bool:
        now = time.monotonic()
        self._failures = [t for t in self._failures if now - t < LOCK_SECONDS]
        if len(self._failures) >= MAX_FAILURES:
            raise HTTPException(status_code=429, detail="too many attempts, wait a moment")
        ok = hmac.compare_digest(hashlib.sha256(candidate.encode()).digest(), hashlib.sha256(self._password).digest())
        if not ok:
            self._failures.append(now)
        return ok

    def make_token(self, now: float | None = None) -> str:
        expiry = str(int((time.time() if now is None else now) + LIFETIME))
        return f"{expiry}.{hmac.new(self._key, expiry.encode(), hashlib.sha256).hexdigest()}"

    def verify(self, token: str | None, now: float | None = None) -> bool:
        if not token or "." not in token:
            return False
        expiry, _, signature = token.partition(".")
        expected = hmac.new(self._key, expiry.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected) and expiry.isdigit() and int(expiry) > (time.time() if now is None else now)


def require_session(request: Request) -> None:
    """Dependency of every route except /health and the login."""
    if not request.app.state.auth.verify(request.cookies.get(COOKIE)):
        raise HTTPException(status_code=401, detail="not authenticated")
