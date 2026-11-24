"""Protection for a public link: per-visitor rate limit and a daily cap on questions.

Every question costs API credits, so a public demo needs limits. The daily cap
is counted from the audit log, so it survives restarts.
"""

import time
from collections import defaultdict, deque
from datetime import timedelta
from threading import Lock

from fastapi import HTTPException, Request

from app.config import settings
from app.db import AuditEvent, SessionLocal, utcnow

_hits: dict[str, deque] = defaultdict(deque)
_lock = Lock()


def client_ip(request: Request) -> str:
    # Behind the Cloudflare tunnel the real visitor IP is in CF-Connecting-IP.
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "").split(",")[0]
    return forwarded.strip() or (request.client.host if request.client else "unknown")


def is_public_request(request: Request) -> bool:
    """True when the request came through a tunnel or proxy, not straight from this laptop."""
    return bool(request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for"))


def check_limits(request: Request) -> None:
    ip = client_ip(request)
    now = time.monotonic()
    with _lock:
        recent = _hits[ip]
        while recent and now - recent[0] > 60:
            recent.popleft()
        if len(recent) >= settings.rate_limit_per_minute:
            raise HTTPException(status_code=429, detail="Too many questions in one minute. Please wait a moment.")
        recent.append(now)

    since = utcnow() - timedelta(hours=24)
    with SessionLocal() as s:
        today = s.query(AuditEvent).filter(AuditEvent.event_type == "visitor_message",
                                           AuditEvent.created_at >= since).count()
    if today >= settings.max_daily_messages:
        raise HTTPException(status_code=429, detail="The agent reached its daily limit. "
                                                    "Please contact Dionysios directly at gogosdion@gmail.com.")


def reset() -> None:
    """Used by tests."""
    with _lock:
        _hits.clear()
