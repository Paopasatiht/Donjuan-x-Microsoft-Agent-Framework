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

# Static starter cards — pre-written questions + answers shown instantly on the homepage.
# Edit these directly to update what users see; no AI call is made for this endpoint.
_PREFILLED_STARTERS = [
    {
        "label": "FEAR",
        "text": "ผมชอบสาวคนนึงแต่ไม่กล้าเข้าไปคุย",
        "answer": (
            "## DIAGNOSE\n"
            "ตอนนี้คุณอยู่ในโหมด AFC (Average Frustrated Chump) เล็กๆ เพราะสมองกำลังยกเธอขึ้นเป็น \"ศาลตัดสิน\" แทนที่จะเป็นคนธรรมดาที่คุณจะเข้าไปทำความรู้จัก\n\n"
            "## NAME\n"
            "นี่คือแพทเทิร์น \"กลัวก่อนเริ่ม\" ไม่ใช่แพ้เธอ แพ้ความกลัวของตัวเอง\n\n"
            "## PRESCRIBE — ทำ 3 อย่างวันนี้เลย\n"
            "- เข้าไปทักสั้นๆ 1 ประโยค: \"หวัดดี เราเห็นเธอแล้วอยากมาทัก\"\n"
            "- อย่าคิดบทพูดยาว ใช้แค่ เปิด-ถาม-ปิด\n"
            "- เป้าหมายวันนี้ไม่ใช่ \"ต้องได้ผล\" แต่คือ ต้องเริ่มบทสนทนา 1 ครั้ง\n\n"
            "## REFERENCE\n"
            "- Theory 29: ต้องกล้ากระโจนเข้าไปคุยกับสาวสวย\n"
            "- Theory 10: เธอจะจัดคุณไว้เป็น แฟน / เพื่อน / คนแปลกหน้า — ถ้าคุณไม่เข้าไปพูด คุณก็อยู่ช่องคนแปลกหน้าตลอด\n"
            "- Red flag: AFC — \"กลัวเธอจะคิดว่า…\" คือโฟกัสผิดทาง\n\n"
            "## CHALLENGE\n"
            "วันนี้ไปทักให้ได้ 1 ครั้ง แล้วกลับมารายงานแบบตรงๆ: คุณพูดประโยคแรกว่าอะไร และเธอตอบยังไง?"
        ),
    },
    {
        "label": "FRIENDZONE",
        "text": "เธอบอกว่าเราเป็นแค่เพื่อนกัน",
        "answer": (
            "## DIAGNOSE\n"
            "ตอนนี้คุณอยู่ในโซน Friendzone ชัดๆ\n\n"
            "เธอวางกรอบไว้แล้วว่า \"ไม่มีแรงดึงดูดแบบรัก/โรแมนติก\" ตั้งแต่จุดเริ่ม ไม่ใช่คุณแพ้แค่คำพูด แต่แพ้เพราะคุณยังไม่ทำให้เกมมีความตึงเครียดทางเพศ (sexual tension) พอ\n\n"
            "## NAME\n"
            "นี่คือ Friendzone + Nice Guy pattern\n\n"
            "ถ้าคุณเคยนิ่ง รอ ช่วยเกินพอดี หรือไม่เคยแสดงเจตนาชัดๆ มาก่อน อันนี้ตรงสูตรเลย\n\n"
            "## PRESCRIBE — ทำ 3 อย่างวันนี้\n"
            "- หยุดทำตัวเป็นเพื่อนบริการ: อย่าคุยเพื่อเอาใจอย่างเดียว\n"
            "- ตอบให้ชัดและนิ่ง: \"เข้าใจ งั้นเราจะคุยกันแบบเพื่อน\" แล้วถอย 1 ก้าว\n"
            "- กลับไปสร้างคุณค่าในตัวเอง: ออกไปเจอคนอื่น ใช้ชีวิต อย่าเอาเธอเป็นศูนย์กลาง\n\n"
            "ถ้าคุณยังอยากให้มีโอกาส ต้องมี sexual tension (แรงดึงดูดทางเพศ) แบบสุภาพและชัดเจนในอนาคต ไม่ใช่ไล่ตามแบบคนขออนุญาตมีตัวตน\n\n"
            "## REFERENCE\n"
            "- Theory 28: Nice Guy ไม่กล้าแสดง sexual interest → โดนขอเป็นเพื่อน\n"
            "- Theory 13: รักคนอื่นไม่ได้ถ้ายังไม่รักตัวเอง\n"
            "- Red flag: \"เราแค่เพื่อนกัน\" = no sexual tension\n\n"
            "## CHALLENGE\n"
            "วันนี้ให้ทำ 1 อย่าง: หยุดทักเธอเพิ่ม 24 ชั่วโมง แล้วกลับมาถามตัวเองว่า\n\n"
            "\"ตอนที่คุยกับเธอ ฉันกำลังพยายามเป็นผู้ชายที่น่าดึงดูด หรือแค่พยายามเป็นคนที่เธอไม่รำคาญ?\""
        ),
    },
    {
        "label": "NICE GUY",
        "text": "ผมดีกับเธอมากแต่เธอไม่สนใจ",
        "answer": (
            "## DIAGNOSE\n"
            "นี่คือ Nice Guy syndrome ชัดๆ — คุณให้เยอะ หวังผลเงียบๆ แล้วพอเธอไม่ตอบ ก็เริ่มเจ็บ\n\n"
            "## NAME\n"
            "ปัญหาไม่ใช่ \"คุณดีไม่พอ\" แต่คือ ดีแบบไม่มีแรงดึงดูด\n\n"
            "**ดีกับเธอมาก ≠ เธอจะสนใจคุณ**\n\n"
            "## PRESCRIBE\n"
            "- หยุดทำแต้มบุญเงียบๆ เลยวันนี้: ไม่ต้องทุ่มเวลา ของขวัญ หรือการเอาใจเกินจำเป็น\n"
            "- เปลี่ยนจาก \"ผู้ให้\" เป็น \"ผู้ชายที่มีชีวิตของตัวเอง\" — ไปยิม ทำงาน เจอเพื่อน มีเป้าหมาย\n"
            "- คุยแบบตรงและเบาๆ ถ้าสนใจจริง: ไม่อ้อม ไม่แบกความคาดหวังไว้คนเดียว\n"
            "  ตัวอย่าง: \"เราโอเคที่จะคุยแบบค่อยเป็นค่อยไป แต่ถ้าไม่อิน เราก็ถอยได้\"\n\n"
            "## REFERENCE\n"
            "- Theory 20: Nice Guy = เพ้อถึงเธอ ในขณะที่ DJ เดินเข้าไปใช้ชีวิตจริง\n"
            "- Theory 28: ไม่กล้าแสดงความสนใจเชิงผู้ชาย = โดนเก็บไว้โซนเพื่อน\n"
            "- Red flag: Nice Guy — \"ผมดีกับเธอมาก แต่...\" = ยกเธอสูง ตัวเองต่ำ\n\n"
            "## CHALLENGE\n"
            "วันนี้ตัด 1 อย่างที่คุณทำเพื่อ \"หวังให้เธอชอบ\" ออกไป แล้วกลับมารายงาน:\n\n"
            "คุณกำลังทำอะไรอยู่ที่จริงๆ แล้วคือการขอความรักแบบไม่พูดตรงๆ?"
        ),
    },
    {
        "label": "SELF-ESTEEM",
        "text": "วิธีสร้าง self-esteem ทำยังไง",
        "answer": (
            "## DIAGNOSE\n"
            "ตอนนี้คือ In-progress — คุณกำลังเริ่มสร้างฐานของตัวเอง ไม่ใช่แค่ \"อยากมั่นใจ\" แบบลมๆแล้งๆ\n\n"
            "## NAME\n"
            "นี่คือการสร้าง Self-esteem (คุณค่าตัวเอง) ไม่ใช่ไปไล่เก็บคำชมจากคนอื่น\n\n"
            "## PRESCRIBE — ทำ 3 อย่างนี้วันนี้เลย\n"
            "- เก็บ 1 ชัยชนะเล็กๆ: ออกกำลังกาย 20 นาที / เก็บห้อง / ทำงานค้าง 1 ชิ้นให้เสร็จ\n"
            "- พูดกับตัวเองแบบคนคุมเกม: \"วันนี้กูทำสิ่งที่ควบคุมได้\" ไม่ใช่ \"วันนี้คนอื่นจะชอบกูไหม\"\n"
            "- เลิกพึ่ง validation (การยืนยันจากคนอื่น): อย่าเช็กว่าใครตอบแชทไหมตลอดวัน แล้วเอาพลังไปลงกับตัวเอง\n\n"
            "จำไว้: self-esteem ไม่ได้เกิดจากการคิดว่าตัวเองเก่ง แต่มาจากการ**พิสูจน์ให้ตัวเองเห็นว่าไว้ใจตัวเองได้**\n\n"
            "## REFERENCE\n"
            "- 4C Framework: แก่นของ DJ คือ Confident / Calm / Control / Challenging — เริ่มจากคุมตัวเองก่อน\n"
            "- James Bond Combo: สบตา นิ่ง เปิด body และใช้เสียงช้าแน่น = ภาพของคนที่เชื่อมาจากข้างใน\n"
            "- Social Proof: คนที่มีคุณค่ามักมีชีวิตของตัวเอง ไม่ได้หมุนรอบใครคนเดียว\n\n"
            "## CHALLENGE\n"
            "วันนี้ทำ \"1 action ที่ทำให้ตัวเองภูมิใจ\" แล้วมารายงาน:\n\n"
            "คุณทำอะไร และหลังทำเสร็จคุณรู้สึกกับตัวเองกี่/10?"
        ),
    },
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

    rate_limiter._increment_user(req.user_id)
    session = _get_or_create_session(req.session_id or req.user_id)

    start_ts = time.time()
    response = await _agent.run(req.message, session=session)
    latency = time.time() - start_ts

    _components["query_logger"].log(
        user_id=req.user_id,
        query=req.message,
        session_id=req.session_id,
        latency_s=latency,
    )

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
        start_ts = time.time()
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
            latency = time.time() - start_ts
            _components["query_logger"].log(
                user_id=req.user_id,
                query=req.message,
                session_id=req.session_id,
                latency_s=latency,
            )
            remaining_after = rate_limiter.get_remaining(req.user_id)
            yield f"data: {json.dumps({'done': True, 'remaining_quota': remaining_after})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/suggestions", response_model=SuggestionsResponse)
async def get_suggestions():
    """Return static starter questions with pre-written answers. No AI call, no token cost."""
    return {"suggestions": _PREFILLED_STARTERS}


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


@app.get("/admin/queries", dependencies=[Depends(verify_admin)])
async def admin_queries(limit: int = 100, offset: int = 0):
    """Get paginated query log (newest first)."""
    ql = _components["query_logger"]
    return {
        "total": ql.total(),
        "offset": offset,
        "limit": limit,
        "entries": ql.get_entries(limit=min(limit, 500), offset=offset),
    }


@app.get("/admin/queries/export", dependencies=[Depends(verify_admin)])
async def admin_queries_export():
    """Download full query log as CSV."""
    from fastapi.responses import StreamingResponse as SR
    import io, csv

    ql = _components["query_logger"]
    entries = ql.get_entries(limit=2000, offset=0)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["ts", "user_id", "session_id", "query", "latency_s"])
    writer.writeheader()
    writer.writerows(entries)
    buf.seek(0)

    now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return SR(
        iter([buf.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=dj_queries_{now_str}.csv"},
    )


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
