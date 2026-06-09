"""
JWT Auth middleware for Histrategy Server.

Verifies tokens signed by Orchestrator (shared JWT_SECRET).
Extracts user_id from token's 'sub' claim.
"""
import os
from typing import Optional

import jwt
from fastapi import Header, HTTPException, status

JWT_SECRET = os.environ.get("JWT_SECRET", "emergence-secret-dev")
JWT_ALGORITHM = "HS256"


def get_current_user_id(authorization: Optional[str] = Header(default=None)) -> str:
    """FastAPI dependency: extract user_id from Bearer JWT.

    Returns the user UUID string from 'sub' claim.
    Raises 401 if token is missing or invalid.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )
    token = authorization[len("Bearer "):]
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
