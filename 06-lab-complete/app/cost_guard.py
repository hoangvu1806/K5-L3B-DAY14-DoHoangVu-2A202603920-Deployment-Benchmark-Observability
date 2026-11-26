"""Cost guard (tiêu chí 8) — theo dõi chi phí LLM trong Redis."""
import logging
from datetime import datetime, timezone

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

logger = logging.getLogger("app.cost_guard")

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_memory_spend: dict[str, float] = {}


def _budget_key() -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"cost:daily:{today}"


def _effective_budget() -> float:
    return min(settings.daily_budget_usd, settings.monthly_budget_usd)


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    key = _budget_key()
    budget = _effective_budget()
    current = _memory_spend.get(key, 0.0)

    if r is not None:
        try:
            current = float(r.get(key) or 0.0)
        except redis.RedisError as exc:
            logger.warning("Redis check_budget fallback: %s", exc)

    if current >= budget:
        raise HTTPException(
            status_code=402,
            detail="Budget exceeded",
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (
        (input_tokens / 1000.0) * PRICE_INPUT_PER_1K
        + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    )
    key = _budget_key()
    _memory_spend[key] = _memory_spend.get(key, 0.0) + cost

    if r is not None:
        try:
            r.incrbyfloat(key, cost)
            r.expire(key, 2 * 86400)
        except redis.RedisError as exc:
            logger.warning("Redis record_cost fallback: %s", exc)

    return cost
