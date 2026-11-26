"""Authentication module: JWT Bearer (primary for users) + X-API-Key (service-to-service)."""
from datetime import datetime, timedelta, timezone
import secrets

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.security.api_key import APIKeyHeader
import jwt

from app.config import settings

JWT_ALGORITHM = "HS256"

bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _signing_secret() -> str:
    return settings.jwt_secret or settings.agent_api_key


def create_access_token(subject: str, role: str = "user") -> dict:
    """Sign and return a stateless HS256 JWT access token."""
    secret = _signing_secret()
    if not secret:
        raise HTTPException(status_code=500, detail="JWT signing secret is not configured")

    now = datetime.now(timezone.utc)
    expires_delta = timedelta(minutes=settings.jwt_expire_minutes)
    exp = now + expires_delta
    payload = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": int(expires_delta.total_seconds()),
        "claims": {"sub": subject, "role": role, "exp": int(exp.timestamp())},
    }


def authenticate_for_token(username: str, passcode: str) -> dict:
    """Validate login passcode against configured secret and mint a JWT."""
    expected = settings.agent_api_key
    if not expected or not passcode or not secrets.compare_digest(passcode, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    role = "admin" if username.strip().lower() in {"admin", "teacher"} else "user"
    return create_access_token(subject=username.strip(), role=role)


def verify_jwt_token(token: str) -> dict:
    """Verify HS256 JWT signature & expiry and return caller context."""
    secret = _signing_secret()
    if not secret:
        raise HTTPException(status_code=401, detail="Authentication unavailable")
    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=401,
            detail="JWT token expired. Please request a new token via POST /auth/token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid JWT token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    sub = str(payload.get("sub") or "anonymous")
    role = str(payload.get("role") or "user")
    return {
        "identity": f"jwt:{sub}",
        "auth_type": "jwt",
        "sub": sub,
        "role": role,
    }


def verify_auth(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    api_key: str | None = Security(api_key_header),
) -> dict:
    """Accept Authorization: Bearer <JWT> (primary) or X-API-Key (service-to-service)."""
    if credentials and credentials.scheme.lower() == "bearer" and credentials.credentials:
        return verify_jwt_token(credentials.credentials)

    expected = settings.agent_api_key
    if api_key and expected and secrets.compare_digest(api_key, expected):
        return {
            "identity": f"apikey:{api_key}",
            "auth_type": "api_key",
            "sub": "service",
            "role": "service",
        }

    raise HTTPException(
        status_code=401,
        detail="Authentication required: provide Authorization: Bearer <JWT> (or X-API-Key for services)",
        headers={"WWW-Authenticate": "Bearer"},
    )
