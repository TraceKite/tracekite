"""Bearer-token auth, JSONL audit log, and rate limits for expensive routes.

Single-token scheme for v1 (design §9); an SSO-fronted deployment replaces
this at the proxy layer. Requests fail closed when API_TOKEN is unset.
"""

import hashlib
import hmac
import json
import logging
import os
import threading
import time
from collections import deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from tracekite.config import settings

logger = logging.getLogger(__name__)

PUBLIC_PATHS = {"/", "/health", "/docs", "/openapi.json", "/redoc"}
MUTATING_METHODS = {"POST", "DELETE", "PUT", "PATCH"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Per-bucket request budgets. A full link run reloads every claim in the graph
# and rewrites Layer-1/2, so it is the most expensive call in the API and needs
# a tighter budget than a read — not no budget at all.
RATE_LIMIT_PER_MINUTE = 30
RATE_LIMITS: tuple[tuple[str, str, int], ...] = (
    ("/api/v2/links/rebuild", "rebuild", 4),
    ("/api/v2/trace", "trace", RATE_LIMIT_PER_MINUTE),
    ("/api/v2/impact", "trace", RATE_LIMIT_PER_MINUTE),
    ("/api/repos/ingest", "ingest", 20),
)


class RateLimiter:
    def __init__(self, limit: int = RATE_LIMIT_PER_MINUTE, window_s: float = 60.0):
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int | None = None) -> bool:
        limit = self.limit if limit is None else limit
        now = time.monotonic()
        # Starlette runs middleware on the event loop but handlers may resume
        # on worker threads; the bucket mutation must not interleave.
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and now - bucket[0] > self.window_s:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True


def _rate_bucket(path: str) -> tuple[str, int] | None:
    for prefix, bucket, limit in RATE_LIMITS:
        if path.startswith(prefix):
            return bucket, limit
    return None


_limiter = RateLimiter()


def _token_id(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:8]


def audit(token_id: str, method: str, path: str, status: int) -> None:
    """Append a JSONL audit record for every mutating call (design §9)."""
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "token_id": token_id,
        "method": method,
        "path": path,
        "status": status,
    }
    try:
        path_dir = os.path.dirname(settings.audit_log_path)
        if path_dir:
            os.makedirs(path_dir, exist_ok=True)
        with open(settings.audit_log_path, "a") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError as exc:
        logger.error("Audit log write failed: %s", exc)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS or not path.startswith("/api"):
            return await call_next(request)

        # Auth disabled entirely: no token is required for anything, writes
        # included. Rate limiting and the audit log stay on — they are not
        # authentication, and they are the only remaining record of who did
        # what. Callers share one bucket since there is no identity.
        if not settings.auth_enabled:
            limited = _rate_bucket(path)
            if limited is not None:
                bucket, limit = limited
                if not _limiter.allow(f"anonymous:{bucket}", limit):
                    audit("anonymous", request.method, path, 429)
                    return JSONResponse(
                        {"detail": f"Rate limit exceeded for {bucket} ({limit}/min)"},
                        status_code=429,
                        headers={"Retry-After": "60"},
                    )
            response = await call_next(request)
            if request.method in MUTATING_METHODS:
                audit("anonymous", request.method, path, response.status_code)
            return response

        # Reads may be served anonymously when the operator opts in. Writes
        # never can: /api/repos/ingest makes this host clone an arbitrary URL,
        # and DELETE destroys ingested data. Keeping that split means the UI
        # stops demanding a token to look at the graph without opening the
        # dangerous surface.
        is_read = request.method in SAFE_METHODS
        if is_read and settings.allow_anonymous_reads:
            return await call_next(request)

        if not settings.api_token:
            detail = (
                "API_TOKEN is not configured; mutating API access disabled"
                if settings.allow_anonymous_reads
                else "API_TOKEN is not configured; all API access disabled"
            )
            return JSONResponse({"detail": detail}, status_code=503)

        header = request.headers.get("authorization", "")
        expected = f"Bearer {settings.api_token}"
        if not hmac.compare_digest(header.encode(), expected.encode()):
            audit("anonymous", request.method, path, 401)
            return JSONResponse({"detail": "Invalid or missing bearer token"},
                                status_code=401)

        token_id = _token_id(settings.api_token)
        limited = _rate_bucket(path)
        if limited is not None:
            bucket, limit = limited
            if not _limiter.allow(f"{token_id}:{bucket}", limit):
                audit(token_id, request.method, path, 429)
                return JSONResponse(
                    {"detail": f"Rate limit exceeded for {bucket} "
                               f"({limit}/min)"},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )

        response = await call_next(request)
        if request.method in MUTATING_METHODS:
            audit(token_id, request.method, path, response.status_code)
        return response
