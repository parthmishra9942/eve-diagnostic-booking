from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# Redis-backed limiter that transparently falls back to in-process memory
# storage if Redis becomes unreachable (swallow_errors never fails a request).
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.rate_limit_storage_url or settings.redis_url,
    enabled=settings.rate_limit_enabled,
    swallow_errors=True,
    in_memory_fallback_enabled=True,
)
