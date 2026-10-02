import hashlib
import hmac
from datetime import datetime, timedelta, timezone

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc
from decimal import Decimal
from typing import Any

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=settings.bcrypt_rounds)


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _pwd_context.verify(password, hashed)


def create_access_token(user_id: int, role: str) -> tuple[str, int]:
    """Returns (token, expires_in_seconds)."""
    expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    now = datetime.now(UTC)
    claims = {"sub": str(user_id), "role": role, "iat": now, "exp": now + expires_delta}
    token = jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, int(expires_delta.total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises jose.JWTError if the token is invalid or expired."""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def _canonical_webhook_message(
    event_id: str, booking_id: int, transaction_id: str, status: str, amount: Decimal | float | str
) -> bytes:
    amount_str = f"{Decimal(str(amount)):.2f}"
    return f"{event_id}|{booking_id}|{transaction_id}|{status}|{amount_str}".encode()


def compute_webhook_signature(
    *,
    event_id: str,
    booking_id: int,
    transaction_id: str,
    status: str,
    amount: Decimal | float | str,
    secret: str | None = None,
) -> str:
    """HMAC-SHA256 over a canonical string of the webhook fields."""
    key = (secret or settings.webhook_secret).encode()
    message = _canonical_webhook_message(event_id, booking_id, transaction_id, str(status), amount)
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def verify_webhook_signature(
    *,
    signature: str,
    event_id: str,
    booking_id: int,
    transaction_id: str,
    status: str,
    amount: Decimal | float | str,
) -> bool:
    expected = compute_webhook_signature(
        event_id=event_id, booking_id=booking_id, transaction_id=transaction_id, status=status, amount=amount
    )
    return hmac.compare_digest(expected, signature)
