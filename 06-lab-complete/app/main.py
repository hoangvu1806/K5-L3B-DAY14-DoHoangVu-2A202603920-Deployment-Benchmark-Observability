"""Production AI Agent — Part 6 Final Project."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import signal
import sys
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from app.auth import authenticate_for_token, verify_auth
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


class TokenRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    passcode: str = Field(..., min_length=1, max_length=256)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default="anonymous", max_length=128)


APP_DIR = Path(__file__).resolve().parent
INDEX_HTML_PATH = APP_DIR / "index.html"
STATIC_DIR = APP_DIR / "static"
ALLOWED_ASSETS = {
    "dashboard.png",
    "running.png",
    "test.png",
    "grafana-dashboard.png",
    "jaeger-slow-trace.png",
    "jaeger-error-trace.png",
    "prometheus-alert-firing.png",
}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def landing_page():
    """Trang giới thiệu hành trình Day 14 và bảng kiểm thử live API."""
    if not INDEX_HTML_PATH.exists():
        return HTMLResponse("<h1>Production AI Agent</h1>", status_code=200)
    return HTMLResponse(INDEX_HTML_PATH.read_text(encoding="utf-8"))


@app.get("/assets/{filename}", include_in_schema=False)
def serve_asset(filename: str):
    """Phục vụ các ảnh bằng chứng của bài lab theo danh sách trắng an toàn."""
    if filename not in ALLOWED_ASSETS:
        raise HTTPException(status_code=404, detail="Asset not found")
    path = STATIC_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(path, media_type="image/png")


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


@app.post("/auth/token")
def issue_token(body: TokenRequest):
    """Issue a signed HS256 JWT token for Bearer authentication on /ask."""
    token_data = authenticate_for_token(body.username, body.passcode)
    log_event("jwt_issued", sub=token_data["claims"]["sub"], role=token_data["claims"]["role"])
    return token_data


@app.post("/ask")
def ask(body: AskRequest, caller: dict = Depends(verify_auth)):
    """Protected agent endpoint: JWT/API-Key auth → rate limit → cost guard → LLM → record cost."""
    check_rate_limit(caller["identity"])
    check_budget()

    answer = llm_ask(body.question)
    input_tokens = max(1, len(body.question) // 4)
    output_tokens = max(1, len(answer) // 4)
    cost = record_cost(input_tokens, output_tokens)

    effective_user = caller["sub"] if caller["auth_type"] == "jwt" else body.user_id

    log_event(
        "ask_completed",
        auth_type=caller["auth_type"],
        user_id=effective_user,
        role=caller["role"],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost, 8),
    )
    return {
        "question": body.question,
        "answer": answer,
        "user_id": effective_user,
        "auth": {
            "type": caller["auth_type"],
            "sub": caller["sub"],
            "role": caller["role"],
        },
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 8),
        },
    }
