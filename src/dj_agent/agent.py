"""DJ Agent factory — builds the Agent with middleware stack."""

import logging
import redis as redis_lib
from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient

from .config import settings
from .knowledge import DJ_SYSTEM_PROMPT
from .middleware.cost_tracker import CostTrackerMiddleware
from .middleware.guardrails import GuardrailsMiddleware
from .middleware.query_logger import RedisQueryLogger, query_logger_middleware
from .middleware.rate_limiter import RateLimiterMiddleware
from .tools import init_knowledge_store, retrieve_dj_knowledge

logger = logging.getLogger(__name__)


class InMemoryRedis:
    """Minimal Redis-like in-memory store for when Redis is unavailable."""

    def __init__(self):
        self._data: dict[str, str | set] = {}

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value):
        self._data[key] = value

    def incr(self, key):
        val = int(self._data.get(key, 0)) + 1
        self._data[key] = str(val)
        return val

    def incrby(self, key, amount):
        val = int(self._data.get(key, 0)) + amount
        self._data[key] = str(val)
        return val

    def expire(self, key, seconds):
        pass  # No TTL in memory

    def sadd(self, key, *values):
        if key not in self._data:
            self._data[key] = set()
        self._data[key].update(values)

    def scard(self, key):
        s = self._data.get(key, set())
        return len(s) if isinstance(s, set) else 0

    def smembers(self, key):
        s = self._data.get(key, set())
        return s if isinstance(s, set) else set()

    def lpush(self, key, *values):
        if key not in self._data:
            self._data[key] = []
        for v in reversed(values):
            self._data[key].insert(0, v)
        return len(self._data[key])

    def ltrim(self, key, start, end):
        lst = self._data.get(key, [])
        self._data[key] = lst[start: end + 1 if end >= 0 else None]

    def lrange(self, key, start, end):
        lst = self._data.get(key, [])
        return lst[start: end + 1 if end >= 0 else None]

    def llen(self, key):
        return len(self._data.get(key, []))

    def ping(self):
        return True


def _get_redis():
    """Create a Redis client, fallback to in-memory if unavailable."""
    try:
        r = redis_lib.from_url(settings.redis_url, decode_responses=True)
        r.ping()
        logger.info(f"Connected to Redis at {settings.redis_url}")
        return r
    except Exception as e:
        logger.warning(f"Redis unavailable ({e}), using in-memory fallback")
        return InMemoryRedis()


def build_dj_agent() -> tuple[Agent, dict]:
    """Build and return the DJ Agent with all middleware.

    Returns:
        (agent, components) where components contains middleware instances
        for use by the API layer (e.g., rate_limiter for quota checks).
    """
    # Initialize knowledge embeddings
    init_knowledge_store()

    # OpenAI client (direct, not Azure)
    client = OpenAIChatClient(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
    )

    # Redis
    redis_client = _get_redis()

    # Middleware stack
    cost_tracker = CostTrackerMiddleware(
        redis_client=redis_client,
        price_input_per_mtok=settings.price_input_per_mtok,
        price_output_per_mtok=settings.price_output_per_mtok,
    )

    rate_limiter = RateLimiterMiddleware(
        redis_client=redis_client,
        base_daily_quota=settings.daily_quota_per_user,
        monthly_budget_usd=settings.monthly_budget_usd,
        cost_tracker=cost_tracker,
    )

    guardrails = GuardrailsMiddleware()

    # Build agent
    agent = Agent(
        name="donjuan",
        client=client,
        instructions=DJ_SYSTEM_PROMPT,
        tools=[retrieve_dj_knowledge],
        middleware=[
            guardrails,
            query_logger_middleware,
            cost_tracker,
        ],
    )

    query_logger = RedisQueryLogger(redis_client)

    components = {
        "redis": redis_client,
        "cost_tracker": cost_tracker,
        "rate_limiter": rate_limiter,
        "query_logger": query_logger,
    }

    logger.info(f"DJ Agent built — model={settings.openai_model}, quota={settings.daily_quota_per_user}/day, budget=${settings.monthly_budget_usd}/month")
    return agent, components
