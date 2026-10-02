import json
import logging
import time
from typing import Any

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger(__name__)

_BREAKER_SECONDS = 30.0


class CacheService:
    """Thin, failure-tolerant wrapper around Redis.

    Every operation swallows connection errors and degrades to a cache miss, so an
    unreachable Redis never breaks an API call. After a failure a short circuit
    breaker skips Redis entirely so requests don't each pay the connect timeout.
    """

    def __init__(self, url: str, enabled: bool = True, default_ttl: int = 60):
        self._url = url
        self._enabled = enabled
        self._default_ttl = default_ttl
        self._client: Any = None
        self._disabled_until = 0.0

    def _get_client(self) -> Any | None:
        if not self._enabled or time.monotonic() < self._disabled_until:
            return None
        if self._client is None:
            self._client = redis.from_url(
                self._url, socket_connect_timeout=0.5, socket_timeout=0.5, decode_responses=True
            )
        return self._client

    def _trip(self, op: str, exc: Exception) -> None:
        self._disabled_until = time.monotonic() + _BREAKER_SECONDS
        logger.warning("cache unavailable, falling back to database", extra={"cache_op": op, "error": str(exc)})

    async def get_json(self, key: str) -> Any | None:
        client = self._get_client()
        if client is None:
            return None
        try:
            raw = await client.get(key)
            return json.loads(raw) if raw is not None else None
        except Exception as exc:  # noqa: BLE001 - cache must never break requests
            self._trip("get", exc)
            return None

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        client = self._get_client()
        if client is None:
            return
        try:
            await client.set(key, json.dumps(value), ex=ttl or self._default_ttl)
        except Exception as exc:  # noqa: BLE001
            self._trip("set", exc)

    async def get_version(self, namespace: str) -> int:
        client = self._get_client()
        if client is None:
            return 0
        try:
            value = await client.get(f"version:{namespace}")
            return int(value) if value is not None else 0
        except Exception as exc:  # noqa: BLE001
            self._trip("get_version", exc)
            return 0

    async def bump_version(self, namespace: str) -> None:
        """Invalidates every cached key built from this namespace's version."""
        client = self._get_client()
        if client is None:
            return
        try:
            await client.incr(f"version:{namespace}")
        except Exception as exc:  # noqa: BLE001
            self._trip("bump_version", exc)

    async def ping(self) -> bool:
        client = self._get_client()
        if client is None:
            return False
        try:
            return bool(await client.ping())
        except Exception as exc:  # noqa: BLE001
            self._trip("ping", exc)
            return False

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._client = None


cache = CacheService(settings.redis_url, settings.cache_enabled, settings.cache_ttl_seconds)
