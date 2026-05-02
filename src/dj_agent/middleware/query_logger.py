"""Query logging — console + Redis-backed persistent store."""

import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from agent_framework import AgentContext

logger = logging.getLogger(__name__)

_QUERY_LOG_KEY = "dj:query_log"
_QUERY_LOG_MAX = 2000  # keep latest N entries


class RedisQueryLogger:
    """Save every user query to a Redis LIST for admin review."""

    def __init__(self, redis_client) -> None:
        self.redis = redis_client

    def log(self, user_id: str, query: str, session_id: str | None = None, latency_s: float = 0.0) -> None:
        entry = json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "session_id": session_id or "",
            "query": query[:500],
            "latency_s": round(latency_s, 2),
        }, ensure_ascii=False)
        self.redis.lpush(_QUERY_LOG_KEY, entry)
        self.redis.ltrim(_QUERY_LOG_KEY, 0, _QUERY_LOG_MAX - 1)

    def get_entries(self, limit: int = 100, offset: int = 0) -> list[dict]:
        raw = self.redis.lrange(_QUERY_LOG_KEY, offset, offset + limit - 1)
        if not raw:
            return []
        return [json.loads(r) for r in raw]

    def total(self) -> int:
        return self.redis.llen(_QUERY_LOG_KEY) or 0


async def query_logger_middleware(
    context: AgentContext,
    call_next: Callable[[], Awaitable[None]],
) -> None:
    """Lightweight console logger (kept for agent middleware chain)."""
    last_message = context.messages[-1] if context.messages else None
    query_text = last_message.text if last_message else ""
    start = time.perf_counter()
    await call_next()
    elapsed = time.perf_counter() - start
    logger.info(json.dumps({
        "event": "user_query",
        "query": query_text[:200],
        "latency_s": round(elapsed, 2),
    }, ensure_ascii=False))


QueryLoggerMiddleware = query_logger_middleware
