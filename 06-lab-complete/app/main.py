"""Production AI Agent — Part 6 Final Project."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import signal
import sys
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import close_redis, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Format every app log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _setup_logging() -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    app_logger = logging.getLogger("app")
    app_logger.handlers.clear()
    app_logger.addHandler(handler)
    app_logger.setLevel(logging.DEBUG if settings.debug else logging.INFO)
    app_logger.propagate = False
    return app_logger


logger = _setup_logging()
START_TIME = time.time()
_sigterm_wrapped = False


def log_event(event: str, **fields) -> None:
    """Emit a structured JSON log line."""
    logger.info(event, extra={"extra_fields": {"event": event, **fields}})


def _install_sigterm_logger() -> None:
    global _sigterm_wrapped
    if _sigterm_wrapped:
        return
    _sigterm_wrapped = True
    previous = signal.getsignal(signal.SIGTERM)

    def _on_sigterm(signum, frame):
        log_event("sigterm", signal=signum)
        if callable(previous):
            previous(signum, frame)

    signal.signal(signal.SIGTERM, _on_sigterm)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and graceful shutdown lifecycle."""
    _install_sigterm_logger()
    log_event("startup", environment=settings.environment, port=settings.port)
    yield
    log_event("shutdown")
    close_redis()


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        ms = round((time.perf_counter() - start) * 1000, 1)
        log_event("http_request", method=request.method, path=request.url.path, status=status, ms=ms)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log_event("unhandled_error", path=request.url.path, error=type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default="anonymous", max_length=128)


@app.get("/health")
def health():
    """Liveness probe — luôn trả 200 khi process còn chạy."""
    return {
        "status": "ok",
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
    }


@app.get("/ready")
def ready():
    """Readiness probe — 200 khi Redis sẵn sàng, 503 khi mất kết nối Redis."""
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis not connected")
    return {"status": "ready", "redis": "ok"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    """Protected agent endpoint: auth → rate limit → cost guard → LLM → record cost."""
    check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)
    input_tokens = max(1, len(body.question) // 4)
    output_tokens = max(1, len(answer) // 4)
    cost = record_cost(input_tokens, output_tokens)

    log_event(
        "ask_completed",
        user_id=body.user_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost, 8),
    )
    return {
        "question": body.question,
        "answer": answer,
        "user_id": body.user_id,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 8),
        },
    }
