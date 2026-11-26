"""Rate limiting (tiêu chí 7) — sliding window 60s lưu trong Redis."""
import hashlib
import logging
import time
import uuid
from collections import defaultdict, deque

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

logger = logging.getLogger("app.rate_limiter")
WINDOW_SECONDS = 60
_fallback_windows: dict[str, deque[float]] = defaultdict(deque)


def _rate_key(api_key: str) -> str:
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
    return f"ratelimit:{digest}"


def _check_memory_fallback(redis_key: str, limit: int, now: float) -> None:
    window = _fallback_windows[redis_key]
    cutoff = now - WINDOW_SECONDS
    while window and window[0] <= cutoff:
        window.popleft()
    if len(window) >= limit:
        retry_after = max(1, int(window[0] + WINDOW_SECONDS - now) + 1)
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
    window.append(now)


def check_rate_limit(key: str) -> None:
    """Giới hạn RATE_LIMIT_PER_MINUTE request / 60s cho mỗi API key."""
    limit = settings.rate_limit_per_minute
    now = time.time()
    window_start = now - WINDOW_SECONDS
    redis_key = _rate_key(key)

    if r is None:
        _check_memory_fallback(redis_key, limit, now)
        return

    try:
        r.zremrangebyscore(redis_key, 0, window_start)
        current_count = int(r.zcard(redis_key))
        if current_count >= limit:
            oldest = r.zrange(redis_key, 0, 0, withscores=True)
            retry_after = (
                max(1, min(WINDOW_SECONDS, int(oldest[0][1] + WINDOW_SECONDS - now) + 1))
                if oldest
                else WINDOW_SECONDS
            )
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )

        member = f"{now:.6f}:{uuid.uuid4().hex[:8]}"
        pipe = r.pipeline()
        pipe.zadd(redis_key, {member: now})
        pipe.expire(redis_key, WINDOW_SECONDS + 5)
        pipe.execute()
    except HTTPException:
        raise
    except redis.RedisError as exc:
        logger.warning("Redis rate_limiter fallback: %s", exc)
        _check_memory_fallback(redis_key, limit, now)
