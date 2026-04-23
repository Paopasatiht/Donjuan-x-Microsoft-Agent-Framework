"""AgentMiddleware that enforces per-user daily quotas with auto-scaling."""

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from agent_framework import AgentContext, AgentMiddleware, AgentResponse, Message

logger = logging.getLogger(__name__)


class RateLimiterMiddleware(AgentMiddleware):
    """Rate limit users based on daily quota. Auto-scales quota based on monthly spend."""

    def __init__(
        self,
        redis_client,
        base_daily_quota: int = 20,
        monthly_budget_usd: float = 50.0,
        cost_tracker=None,
    ) -> None:
        self.redis = redis_client
        self.base_daily_quota = base_daily_quota
        self.monthly_budget = monthly_budget_usd
        self.cost_tracker = cost_tracker

    def get_current_quota(self) -> int:
        """Auto-scale daily quota based on monthly spend."""
        if self.cost_tracker is None:
            return self.base_daily_quota

        spend = self.cost_tracker.get_monthly_spend()
        if spend >= self.monthly_budget:
            return 0  # Service suspended
        elif spend > self.monthly_budget * 0.96:  # >$48
            return 5
        elif spend > self.monthly_budget * 0.80:  # >$40
            return 10
        elif spend > self.monthly_budget * 0.60:  # >$30
            return 15
        else:
            return self.base_daily_quota

    def get_user_count(self, user_id: str) -> int:
        """Get how many queries this user has made today."""
        now = datetime.now(timezone.utc)
        key = f"dj:user:{user_id}:daily:{now.strftime('%Y-%m-%d')}"
        return int(self.redis.get(key) or 0)

    def get_remaining(self, user_id: str) -> int:
        """Get remaining quota for a user."""
        return max(0, self.get_current_quota() - self.get_user_count(user_id))

    def _increment_user(self, user_id: str) -> None:
        """Increment user's daily counter and track unique users."""
        now = datetime.now(timezone.utc)
        key = f"dj:user:{user_id}:daily:{now.strftime('%Y-%m-%d')}"
        self.redis.incr(key)
        self.redis.expire(key, 2 * 86400)

        users_key = f"dj:users:daily:{now.strftime('%Y-%m-%d')}"
        self.redis.sadd(users_key, user_id)
        self.redis.expire(users_key, 2 * 86400)

    async def process(
        self,
        context: AgentContext,
        call_next: Callable[[], Awaitable[None]],
    ) -> None:
        # Extract user_id from context metadata
        user_id = getattr(context, "user_id", None) or "anonymous"
        current_quota = self.get_current_quota()
        user_count = self.get_user_count(user_id)

        if current_quota == 0:
            context.terminate = True
            context.result = AgentResponse(
                messages=[Message(role="assistant", contents=["ระบบปิดปรับปรุงชั่วคราว เนื่องจาก budget ประจำเดือนหมดแล้ว กลับมาใหม่เดือนหน้านะ"])]
            )
            logger.warning(f"Service suspended — monthly budget exhausted. User: {user_id}")
            return

        if user_count >= current_quota:
            context.terminate = True
            context.result = AgentResponse(
                messages=[Message(role="assistant", contents=[f"วันนี้ครบ {current_quota} ข้อแล้ว มาใหม่พรุ่งนี้นะ 💪"])]
            )
            logger.info(f"Rate limited user {user_id}: {user_count}/{current_quota}")
            return

        # Increment user counter
        now = datetime.now(timezone.utc)
        key = f"dj:user:{user_id}:daily:{now.strftime('%Y-%m-%d')}"
        self.redis.incr(key)
        self.redis.expire(key, 2 * 86400)  # 2 days TTL

        # Track unique users
        users_key = f"dj:users:daily:{now.strftime('%Y-%m-%d')}"
        self.redis.sadd(users_key, user_id)
        self.redis.expire(users_key, 2 * 86400)

        await call_next()
