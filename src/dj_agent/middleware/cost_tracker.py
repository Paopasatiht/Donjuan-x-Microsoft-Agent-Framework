"""ChatMiddleware that tracks token usage and cost per request in Redis."""

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from agent_framework import ChatContext, ChatMiddleware

logger = logging.getLogger(__name__)


class CostTrackerMiddleware(ChatMiddleware):
    """Track tokens and cost after each LLM call. Stores in Redis."""

    def __init__(self, redis_client, price_input_per_mtok: float, price_output_per_mtok: float) -> None:
        self.redis = redis_client
        self.price_input = price_input_per_mtok
        self.price_output = price_output_per_mtok

    def _compute_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens * self.price_input + completion_tokens * self.price_output) / 1_000_000

    async def process(
        self,
        context: ChatContext,
        call_next: Callable[[], Awaitable[None]],
    ) -> None:
        await call_next()

        # Try to extract usage from the response
        usage = getattr(context, "usage", None)
        if usage is None:
            return

        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        cost = self._compute_cost(prompt_tokens, completion_tokens)

        now = datetime.now(timezone.utc)
        month_key = f"dj:cost:monthly:{now.strftime('%Y-%m')}"
        day_key = f"dj:cost:daily:{now.strftime('%Y-%m-%d')}"

        # Accumulate monthly and daily cost (stored as cents to avoid float issues)
        cost_cents = int(cost * 100_000)  # microcents for precision
        self.redis.incrby(month_key, cost_cents)
        self.redis.incrby(day_key, cost_cents)
        self.redis.expire(month_key, 35 * 86400)  # 35 days
        self.redis.expire(day_key, 2 * 86400)  # 2 days

        # Increment total queries counter for today
        queries_key = f"dj:queries:daily:{now.strftime('%Y-%m-%d')}"
        self.redis.incr(queries_key)
        self.redis.expire(queries_key, 2 * 86400)

        logger.info(
            "cost_tracked",
            extra={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": cost,
                "monthly_total_microcents": self.redis.get(month_key),
            },
        )

    def get_monthly_spend(self) -> float:
        """Get current month's total spend in USD."""
        now = datetime.now(timezone.utc)
        month_key = f"dj:cost:monthly:{now.strftime('%Y-%m')}"
        microcents = int(self.redis.get(month_key) or 0)
        return microcents / 100_000

    def get_daily_queries(self) -> int:
        """Get today's total query count."""
        now = datetime.now(timezone.utc)
        queries_key = f"dj:queries:daily:{now.strftime('%Y-%m-%d')}"
        return int(self.redis.get(queries_key) or 0)
