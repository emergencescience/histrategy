"""
JWT Auth middleware for Histrategy Server.

Verifies tokens signed by Orchestrator (shared JWT_SECRET).
Extracts user_id from token's 'sub' claim.

DEV_BYPASS_TOKEN: If set and the request's Bearer token matches it,
bypasses JWT verification and returns a hardcoded test user_id.
This is for automated testing / AI agent access only.
"""

import os

import jwt
from fastapi import Header, HTTPException, status

JWT_SECRET = os.environ.get("JWT_SECRET", "emergence-secret-dev")
JWT_ALGORITHM = "HS256"
DEV_BYPASS_TOKEN = os.environ.get("DEV_BYPASS_TOKEN", "")
DEV_BYPASS_USER = os.environ.get("DEV_BYPASS_USER", "dev-agent-001")


def get_current_user_id(authorization: str | None = Header(default=None)) -> str:
    """FastAPI dependency: extract user_id from Bearer JWT.

    Returns the user UUID string from 'sub' claim.
    Raises 401 if token is missing or invalid.

    If DEV_BYPASS_TOKEN is set and matches the Bearer token,
    returns DEV_BYPASS_USER without JWT verification.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )
    token = authorization[len("Bearer ") :]

    # DEV_BYPASS_TOKEN: skip JWT verification for agent testing
    if DEV_BYPASS_TOKEN and token == DEV_BYPASS_TOKEN:
        return DEV_BYPASS_USER

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token missing 'sub' claim")
        return str(user_id)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
