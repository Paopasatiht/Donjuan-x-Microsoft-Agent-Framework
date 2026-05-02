"""Pydantic models for API request/response."""

from pydantic import BaseModel


class ChatRequest(BaseModel):
    user_id: str
    message: str
    session_id: str | None = None  # page-level session; None = stateless


class ChatResponse(BaseModel):
    response: str
    remaining_quota: int
    tokens_used: int | None = None


class UsageResponse(BaseModel):
    user_id: str
    queries_today: int
    daily_limit: int
    remaining: int


class AdminStatsResponse(BaseModel):
    total_queries_today: int
    unique_users_today: int
    monthly_spend_usd: float
    monthly_budget_usd: float
    current_daily_limit: int
    active_sessions: int


class AdminUserStats(BaseModel):
    user_id: str
    queries_today: int
    total_queries: int
    total_cost_usd: float


class SuggestionItem(BaseModel):
    label: str
    text: str


class SuggestionsResponse(BaseModel):
    suggestions: list[SuggestionItem]
