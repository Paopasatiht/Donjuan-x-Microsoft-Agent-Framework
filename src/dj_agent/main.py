"""FastAPI backend for DJ Agent v2."""

import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .agent import build_dj_agent
from .config import settings
from .schemas import (
    AdminStatsResponse,
    AdminUserStats,
    ChatRequest,
    ChatResponse,
    UsageResponse,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Global state (set in lifespan)
_agent = None
_components = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _agent, _components
    logger.info("Starting DJ Agent v2...")
    _agent, _components = build_dj_agent()
    logger.info("DJ Agent v2 ready!")
    yield
    logger.info("Shutting down DJ Agent v2...")


app = FastAPI(
    title="DJ Agent v2",
    description="Don Juan Dating Coach — powered by Microsoft Agent Framework",
    version="1.0.0",
    lifespan=lifespan,
    root_path=settings.root_path,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Auth dependency for admin endpoints
# ---------------------------------------------------------------------------

async def verify_admin(x_admin_key: str = Header(None)):
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "model": settings.openai_model}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send a message to DJ Agent."""
    rate_limiter = _components["rate_limiter"]

    # Check rate limit at API level (with proper user_id)
    remaining = rate_limiter.get_remaining(req.user_id)
    if remaining <= 0:
        quota = rate_limiter.get_current_quota()
        if quota == 0:
            return ChatResponse(
                response="ระบบปิดปรับปรุงชั่วคราว เนื่องจาก budget ประจำเดือนหมดแล้ว กลับมาใหม่เดือนหน้านะ",
                remaining_quota=0,
            )
        return ChatResponse(
            response=f"วันนี้ครบ {quota} ข้อแล้ว มาใหม่พรุ่งนี้นะ 💪",
            remaining_quota=0,
        )

    # Increment user counter
    rate_limiter._increment_user(req.user_id)

    # Create session for this user
    session = _agent.create_session(session_id=req.user_id)

    # Run agent
    response = await _agent.run(req.message, session=session)

    # Get updated remaining after this request
    remaining_after = rate_limiter.get_remaining(req.user_id)

    return ChatResponse(
        response=response.text or "",
        remaining_quota=remaining_after,
        tokens_used=None,
    )


@app.get("/usage/{user_id}", response_model=UsageResponse)
async def get_usage(user_id: str):
    """Check remaining quota for a user."""
    rate_limiter = _components["rate_limiter"]
    count = rate_limiter.get_user_count(user_id)
    limit = rate_limiter.get_current_quota()
    return UsageResponse(
        user_id=user_id,
        queries_today=count,
        daily_limit=limit,
        remaining=max(0, limit - count),
    )


# ---------------------------------------------------------------------------
# Admin endpoints (protected)
# ---------------------------------------------------------------------------

@app.get("/admin/stats", response_model=AdminStatsResponse, dependencies=[Depends(verify_admin)])
async def admin_stats():
    """Get system-wide stats (admin only)."""
    redis_client = _components["redis"]
    cost_tracker = _components["cost_tracker"]
    rate_limiter = _components["rate_limiter"]

    now = datetime.now(timezone.utc)
    day_str = now.strftime("%Y-%m-%d")

    total_queries = int(redis_client.get(f"dj:queries:daily:{day_str}") or 0)
    unique_users = redis_client.scard(f"dj:users:daily:{day_str}") or 0
    monthly_spend = cost_tracker.get_monthly_spend()

    return AdminStatsResponse(
        total_queries_today=total_queries,
        unique_users_today=unique_users,
        monthly_spend_usd=round(monthly_spend, 4),
        monthly_budget_usd=settings.monthly_budget_usd,
        current_daily_limit=rate_limiter.get_current_quota(),
        active_sessions=0,  # TODO: track active sessions
    )


@app.get("/admin/users", dependencies=[Depends(verify_admin)])
async def admin_users():
    """Get per-user usage stats (admin only)."""
    redis_client = _components["redis"]
    now = datetime.now(timezone.utc)
    day_str = now.strftime("%Y-%m-%d")

    user_ids = redis_client.smembers(f"dj:users:daily:{day_str}") or set()
    users = []
    for uid in user_ids:
        count = int(redis_client.get(f"dj:user:{uid}:daily:{day_str}") or 0)
        users.append({"user_id": uid, "queries_today": count})

    return {"users": sorted(users, key=lambda x: x["queries_today"], reverse=True)}


@app.get("/admin/spend-history", dependencies=[Depends(verify_admin)])
async def admin_spend_history():
    """Get daily spend for the current month (admin only)."""
    redis_client = _components["redis"]
    now = datetime.now(timezone.utc)

    days = []
    for day in range(1, now.day + 1):
        day_str = f"{now.strftime('%Y-%m')}-{day:02d}"
        microcents = int(redis_client.get(f"dj:cost:daily:{day_str}") or 0)
        if microcents > 0:
            days.append({"date": day_str, "cost_usd": round(microcents / 100_000, 4)})

    return {"spend_history": days}


# ---------------------------------------------------------------------------
# Serve frontend
# ---------------------------------------------------------------------------

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
async def serve_frontend():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin")
async def serve_admin():
    return FileResponse(STATIC_DIR / "admin.html")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run():
    """Run the FastAPI server."""
    import uvicorn
    uvicorn.run(
        "dj_agent.main:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
    )


if __name__ == "__main__":
    if "--devui" in sys.argv:
        # Launch DevUI for debugging
        from agent_framework.devui import serve
        _agent, _components = build_dj_agent()
        serve(entities=[_agent], auto_open=True)
    else:
        run()
