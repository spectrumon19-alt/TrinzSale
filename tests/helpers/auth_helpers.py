"""Auth helper utilities shared across test modules."""

import datetime
import jwt

TEST_SECRET_KEY = "test-only-secret-key-not-for-production"


def make_token(
    user_id: int,
    role: str,
    username: str,
    secret: str = TEST_SECRET_KEY,
    hours_valid: int = 2,
) -> str:
    payload = {
        "user_id": user_id,
        "role": role,
        "username": username,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=hours_valid),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def expired_token(user_id: int = 1, role: str = "Admin", username: str = "old") -> str:
    payload = {
        "user_id": user_id,
        "role": role,
        "username": username,
        "exp": datetime.datetime.utcnow() - datetime.timedelta(hours=1),
    }
    return jwt.encode(payload, TEST_SECRET_KEY, algorithm="HS256")


def tampered_token() -> str:
    """Return a token signed with a wrong secret."""
    payload = {
        "user_id": 1,
        "role": "Admin",
        "username": "hacker",
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=2),
    }
    return jwt.encode(payload, "wrong-secret", algorithm="HS256")


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
