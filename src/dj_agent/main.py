"""FastAPI backend for DJ Agent v2."""

import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI

from .agent import build_dj_agent
from .config import settings
from .schemas import (
    AdminStatsResponse,
    AdminUserStats,
    ChatRequest,
    ChatResponse,
    SuggestionsResponse,
    UsageResponse,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Global state (set in lifespan)
_agent = None
_components = None

# In-memory session store: {session_id: (AgentSession, last_used_ts)}
_active_sessions: dict = {}
_SESSION_TTL = 1800  # 30 min idle → evict


def _get_or_create_session(session_id: str):
    """Return existing session or create a new one. Updates last-used timestamp."""
    now = time.time()
    # Evict stale sessions while we're here
    stale = [k for k, (_, ts) in _active_sessions.items() if now - ts > _SESSION_TTL]
    for k in stale:
        del _active_sessions[k]
    if session_id not in _active_sessions:
        _active_sessions[session_id] = (_agent.create_session(session_id=session_id), now)
    else:
        sess, _ = _active_sessions[session_id]
        _active_sessions[session_id] = (sess, now)
    return _active_sessions[session_id][0]

# Suggestions cache: refreshed every hour
_suggestions_cache: dict = {"items": [], "ts": 0.0}
_SUGGESTIONS_TTL = 3600

_FALLBACK_SUGGESTIONS = [
    {"label": "FEAR", "text": "ผมชอบสาวคนนึงแต่ไม่กล้าเข้าไปคุย"},
    {"label": "FRIENDZONE", "text": "เธอบอกว่าเราเป็นแค่เพื่อนกัน"},
    {"label": "NICE GUY", "text": "ผมดีกับเธอมากแต่เธอไม่สนใจ"},
    {"label": "SELF-ESTEEM", "text": "วิธีสร้าง self-esteem ทำยังไง"},
]


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

    # Reuse page session if provided, else fall back to user_id (stateless)
    session = _get_or_create_session(req.session_id or req.user_id)

    # Run agent
    response = await _agent.run(req.message, session=session)

    # Get updated remaining after this request
    remaining_after = rate_limiter.get_remaining(req.user_id)

    return ChatResponse(
        response=response.text or "",
        remaining_quota=remaining_after,
        tokens_used=None,
    )


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """Stream a response from DJ Agent using Server-Sent Events."""
    rate_limiter = _components["rate_limiter"]

    remaining = rate_limiter.get_remaining(req.user_id)
    if remaining <= 0:
        quota = rate_limiter.get_current_quota()
        msg = (
            "ระบบปิดปรับปรุงชั่วคราว เนื่องจาก budget ประจำเดือนหมดแล้ว"
            if quota == 0
            else f"วันนี้ครบ {quota} ข้อแล้ว มาใหม่พรุ่งนี้นะ 💪"
        )
        async def quota_err():
            yield f"data: {json.dumps({'text': msg})}\n\n"
            yield f"data: {json.dumps({'done': True, 'remaining_quota': 0})}\n\n"
        return StreamingResponse(quota_err(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    rate_limiter._increment_user(req.user_id)

    async def event_gen():
        try:
            session = _get_or_create_session(req.session_id or req.user_id)
            stream = _agent.run(req.message, session=session, stream=True)
            async for update in stream:
                if update.text:
                    yield f"data: {json.dumps({'text': update.text})}\n\n"
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            remaining_after = rate_limiter.get_remaining(req.user_id)
            yield f"data: {json.dumps({'done': True, 'remaining_quota': remaining_after})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/suggestions", response_model=SuggestionsResponse)
async def get_suggestions():
    """Return 4 AI-generated Thai dating questions (cached 1 h, fallback to defaults)."""
    global _suggestions_cache
    now = time.time()
    if now - _suggestions_cache["ts"] < _SUGGESTIONS_TTL and _suggestions_cache["items"]:
        return {"suggestions": _suggestions_cache["items"]}

    try:
        oai = AsyncOpenAI(api_key=settings.openai_api_key)
        result = await oai.chat.completions.create(
            model=settings.openai_model,
            messages=[{
                "role": "user",
                "content": (
                    "สร้าง 4 คำถามภาษาไทยสั้น ๆ ที่คนจะถาม dating coach ชื่อ Don Juan "
                    "หัวข้อ: ความกลัวเข้าหาคนที่ชอบ, friendzone, ถูกมองข้าม, วิธีสร้าง self-esteem "
                    "ตอบเป็น JSON array เท่านั้น ไม่มี markdown: "
                    '[{"label":"TOPIC_EN_MAX_10CHARS","text":"คำถามภาษาไทยไม่เกิน 20 คำ"}] '
                    "4 items"
                ),
            }],
            max_tokens=400,
            temperature=1.1,
        )
        raw = result.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        items = json.loads(raw.strip())
        _suggestions_cache = {"items": items, "ts": now}
        return {"suggestions": items}
    except Exception as e:
        logger.warning(f"Suggestions generation failed ({e}), using fallback")
        return {"suggestions": _FALLBACK_SUGGESTIONS}


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
