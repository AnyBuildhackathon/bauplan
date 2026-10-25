"""Public access: an access code gate and rate limits, for running the backend on the open internet.

With ANYBUILD_ACCESS_CODE unset (local work) nothing here applies. With it set, every route except
GET /api/health and POST /api/access needs a session: POST /api/access trades the code for a
signed token, which the client sends as `Authorization: Bearer`, the `anybuild_session` cookie,
or `?access_token=` (for EventSource and <img>/<video> URLs, which cannot set headers).
The expensive paths (builds, speech, Reson8 tokens) are then also rate limited per session and per IP.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import secrets
import time
from collections import deque
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
from urllib.parse import parse_qs

COOKIE = "anybuild_session"
TOKEN_TTL_S = 24 * 3600
HOUR = 3600.0

# Wrong codes: per IP, and across all IPs so a botnet cannot guess in parallel.
FAILS_PER_IP = (10, 15 * 60)
FAILS_GLOBAL = (200, 15 * 60)
# New sessions per IP, so nobody mints fresh sessions to dodge the per-session limits.
SESSIONS_PER_IP = (30, HOUR)


def access_code() -> str:
    return os.environ.get("ANYBUILD_ACCESS_CODE", "").strip()


def _per_hour(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, "")))
    except ValueError:
        return default


@dataclass(frozen=True)
class Bucket:
    name: str
    noun: str
    per_session: int
    # Per IP is wider than per session: a jury on venue Wi-Fi shares one address.
    per_ip: int


def buckets() -> dict[str, Bucket]:
    builds = _per_hour("ANYBUILD_LIMIT_BUILDS", 20)
    speech = _per_hour("ANYBUILD_LIMIT_SPEECH", 300)
    stt = _per_hour("ANYBUILD_LIMIT_STT", 60)
    cad = _per_hour("ANYBUILD_LIMIT_CAD", 120)
    explain = _per_hour("ANYBUILD_LIMIT_EXPLAIN", 120)
    return {
        "build": Bucket("build", "builds", builds, builds * 3),
        "speech": Bucket("speech", "speech requests", speech, speech * 3),
        "stt": Bucket("stt", "voice sessions", stt, stt * 3),
        "cad": Bucket("cad", "CAD recomputes", cad, cad * 3),
        "explain": Bucket("explain", "explanations", explain, explain * 3),
    }


def bucket_of(method: str, path: str) -> str | None:
    """Which rate limit a request counts against; None for the cheap ones."""

    if method != "POST":
        return None
    # /api/control presses the app's test and rebuild buttons.
    if path in ("/api/prompt", "/api/sketch", "/api/control"):
        return "build"
    # Starting a reference and restoring a version both rebuild with the tools.
    if (path.startswith("/api/library/") and path.endswith("/open")) or (path.startswith("/api/versions/") and path.endswith("/restore")):
        return "build"
    if path == "/api/explain":
        return "explain"
    if path == "/api/voice/speak":
        return "speech"
    if path == "/api/voice/token":
        return "stt"
    if path == "/api/cad/params":
        return "cad"
    return None


class Window:
    """Sliding-window counters, one deque of timestamps per key."""

    def __init__(self) -> None:
        self.hits: dict[str, deque[float]] = {}
        self.adds = 0

    def retry_after(self, key: str, limit: int, window_s: float, now: float) -> float:
        """Seconds until `key` may act again; 0 when it is under `limit` now."""

        q = self.hits.get(key)
        if not q:
            return 0.0
        while q and q[0] <= now - window_s:
            q.popleft()
        if not q:
            del self.hits[key]
            return 0.0
        return q[0] + window_s - now if len(q) >= limit else 0.0

    def add(self, key: str, now: float) -> None:
        self.hits.setdefault(key, deque()).append(now)
        self.adds += 1
        if self.adds % 1000 == 0:
            # Every window is at most an hour; drop keys that have been quiet longer.
            for stale in [k for k, q in self.hits.items() if q[-1] <= now - HOUR]:
                del self.hits[stale]


def _key(code: str) -> bytes:
    # Derived from the code, so tokens survive a restart and changing the code revokes them all.
    return hashlib.sha256(b"anybuild-session\0" + code.encode("utf-8")).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def issue_token(code: str, now: float) -> tuple[str, str, int]:
    """A new session: (token, session id, expiry as a Unix time)."""

    sid = secrets.token_urlsafe(12)
    exp = int(now) + TOKEN_TTL_S
    body = _b64(json.dumps({"sid": sid, "exp": exp}, separators=(",", ":")).encode("utf-8"))
    sig = _b64(hmac.new(_key(code), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}", sid, exp


def verify_token(code: str, token: str, now: float) -> str | None:
    """The session id of a valid, unexpired token, else None."""

    body, _, sig = token.partition(".")
    if not body or not sig:
        return None
    want = _b64(hmac.new(_key(code), body.encode("ascii", "replace"), hashlib.sha256).digest())
    if not hmac.compare_digest(want, sig):
        return None
    try:
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        sid, exp = str(claims["sid"]), int(claims["exp"])
    except (ValueError, KeyError, TypeError):
        return None
    return sid if exp > now else None


def code_matches(code: str, given: str) -> bool:
    # Comparing digests keeps the time independent of both the content and the length.
    a = hashlib.sha256(given.encode("utf-8")).digest()
    b = hashlib.sha256(code.encode("utf-8")).digest()
    return hmac.compare_digest(a, b)


def _wait_text(seconds: float) -> str:
    minutes = max(1, math.ceil(seconds / 60))
    return "in a minute" if minutes == 1 else f"in {minutes} minutes"


class AccessGate:
    """ASGI middleware: the access code check and the rate limits, in front of every route."""

    def __init__(self, app) -> None:
        self.app = app
        self.window = Window()
        self.clock = time.time

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not access_code():
            return await self.app(scope, receive, send)
        method = scope["method"]
        path = scope["path"]
        # CORS preflights carry no credentials; the CORS middleware outside answers them.
        if method == "OPTIONS" or path == "/api/health":
            return await self.app(scope, receive, send)
        if path == "/api/access" and method == "POST":
            return await self._access(scope, receive, send)

        sid = verify_token(access_code(), self._token(scope), self.clock())
        if sid is None:
            return await _json(send, 401, {"detail": "Enter the access code to use AnyBuild.", "access": "required"})
        # Routes can see the caller is a signed-in user.
        scope.setdefault("state", {})["access_session"] = sid
        if path == "/api/access":
            # GET: is this session still good? The client asks before it shows the app.
            return await _json(send, 200, {"ok": True, "access": "granted"})

        name = bucket_of(method, path)
        if name:
            bucket = buckets()[name]
            now = self.clock()
            ip = client_ip(scope)
            wait = max(
                self.window.retry_after(f"{name}:s:{sid}", bucket.per_session, HOUR, now),
                self.window.retry_after(f"{name}:ip:{ip}", bucket.per_ip, HOUR, now),
            )
            if wait > 0:
                detail = f"Hourly limit of {bucket.per_session} {bucket.noun} reached. Try again {_wait_text(wait)}."
                return await _json(send, 429, {"detail": detail, "limit": name}, retry_after=wait)
            self.window.add(f"{name}:s:{sid}", now)
            self.window.add(f"{name}:ip:{ip}", now)
        return await self.app(scope, receive, send)

    async def _access(self, scope, receive, send) -> None:
        now = self.clock()
        ip = client_ip(scope)
        wait = max(
            self.window.retry_after(f"fail:ip:{ip}", *FAILS_PER_IP, now),
            self.window.retry_after("fail:all", *FAILS_GLOBAL, now),
        )
        if wait > 0:
            return await _json(send, 429, {"detail": f"Too many wrong codes. Try again {_wait_text(wait)}."}, retry_after=wait)
        headers = _headers(scope)
        if "application/json" not in headers.get("content-type", "").lower():
            return await _json(send, 415, {"detail": "Content-Type application/json required"})
        try:
            body = json.loads(await _read_body(receive, limit=4096))
            given = str(body.get("code", "")) if isinstance(body, dict) else ""
        except (ValueError, UnicodeDecodeError):
            given = ""
        if not code_matches(access_code(), given.strip()):
            self.window.add(f"fail:ip:{ip}", now)
            self.window.add("fail:all", now)
            return await _json(send, 401, {"detail": "That code is not right.", "access": "required"})
        wait = self.window.retry_after(f"session:ip:{ip}", *SESSIONS_PER_IP, now)
        if wait > 0:
            return await _json(send, 429, {"detail": f"Too many new sessions. Try again {_wait_text(wait)}."}, retry_after=wait)
        self.window.add(f"session:ip:{ip}", now)
        token, _, exp = issue_token(access_code(), now)
        cookie = f"{COOKIE}={token}; Max-Age={TOKEN_TTL_S}; Path=/; HttpOnly; Secure; SameSite=None"
        await _json(send, 200, {"ok": True, "token": token, "expires_at": exp}, cookie=cookie)

    @staticmethod
    def _token(scope) -> str:
        headers = _headers(scope)
        auth = headers.get("authorization", "")
        if auth[:7].lower() == "bearer ":
            return auth[7:].strip()
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        if query.get("access_token"):
            return query["access_token"][0]
        jar = SimpleCookie()
        try:
            jar.load(headers.get("cookie", ""))
        except CookieError:
            return ""
        return jar[COOKIE].value if COOKIE in jar else ""


def client_ip(scope) -> str:
    """The caller's address. Behind a local proxy (Tailscale Funnel, Vite) it is the last X-Forwarded-For hop."""

    peer = (scope.get("client") or ("", 0))[0]
    if peer in ("127.0.0.1", "::1"):
        forwarded = _headers(scope).get("x-forwarded-for", "")
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if hops:
            return hops[-1]
    return peer or "unknown"


def _headers(scope) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


async def _read_body(receive, limit: int) -> bytes:
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if len(body) > limit:
            raise ValueError("body too large")
        if not message.get("more_body"):
            return body


async def _json(send, status: int, payload: dict, retry_after: float = 0, cookie: str | None = None) -> None:
    raw = json.dumps(payload).encode("utf-8")
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode()), (b"cache-control", b"no-store")]
    if retry_after:
        headers.append((b"retry-after", str(math.ceil(retry_after)).encode()))
    if cookie:
        headers.append((b"set-cookie", cookie.encode("latin-1")))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": raw})
