import hmac
import threading
import time
from collections import defaultdict, deque

from fastapi import Header, Request

from .config import get_settings
from .errors import Forbidden, RateLimited


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """Guards administrative actions when ROUTEWISE_ADMIN_TOKEN is configured."""
    expected = get_settings().admin_token
    if not expected:
        return
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise Forbidden("This action requires a valid X-Admin-Token header.")


class _SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_s: float = 60.0) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                raise RateLimited(f"Too many requests; limit is {limit} per minute for this operation.")
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = _SlidingWindowLimiter()


def rate_limited(bucket: str):
    """Per-client in-process rate limit for expensive or externally backed endpoints.
    For multi-instance deployments, replace with a shared store (e.g. Redis)."""

    def dep(request: Request) -> None:
        client = request.client.host if request.client else "unknown"
        limiter.check(f"{bucket}:{client}", get_settings().rate_limit_per_minute)

    return dep
