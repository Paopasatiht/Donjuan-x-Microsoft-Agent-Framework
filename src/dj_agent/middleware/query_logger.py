"""AgentMiddleware that logs every user query as structured JSON."""

import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from agent_framework import AgentContext

logger = logging.getLogger(__name__)


async def query_logger_middleware(
    context: AgentContext,
    call_next: Callable[[], Awaitable[None]],
) -> None:
    """Log every user query with metadata for monitoring."""
    last_message = context.messages[-1] if context.messages else None
    query_text = last_message.text if last_message else ""
    user_id = getattr(context, "user_id", "anonymous")

    start = time.perf_counter()

    await call_next()

    elapsed = time.perf_counter() - start

    log_entry = {
        "event": "user_query",
        "user_id": user_id,
        "query": query_text[:500],  # truncate for safety
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "latency_s": round(elapsed, 2),
    }
    logger.info(json.dumps(log_entry, ensure_ascii=False))


# Alias for backward compat with __init__.py
QueryLoggerMiddleware = query_logger_middleware
