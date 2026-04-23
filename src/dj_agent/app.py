"""Streamlit frontend for DJ Agent v2 — calls the FastAPI backend."""

import streamlit as st
import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

API_BASE = st.sidebar.text_input("API URL", value="http://localhost:8000")
USER_ID = st.sidebar.text_input("User ID", value="user_001")

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="DJ Agent — ดอนฮวน",
    page_icon="🎩",
    layout="centered",
)

# ---------------------------------------------------------------------------
# Custom CSS (dark theme, red/gold palette — ported from DJ_Agent)
# ---------------------------------------------------------------------------

st.markdown("""
<style>
    /* Main background */
    .stApp { background-color: #121212; }

    /* Chat messages */
    .stChatMessage { border-radius: 12px; padding: 12px; margin: 8px 0; }

    /* Hero section */
    .hero-title {
        text-align: center;
        font-size: 2.5rem;
        font-weight: 800;
        background: linear-gradient(135deg, #E53935, #D4A574);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    .hero-subtitle {
        text-align: center;
        color: #D4A574;
        font-size: 1rem;
        margin-bottom: 2rem;
    }

    /* Quota badge */
    .quota-badge {
        text-align: center;
        padding: 8px 16px;
        border-radius: 20px;
        background: #1E1E1E;
        border: 1px solid #333;
        color: #D4A574;
        font-size: 0.9rem;
        margin-bottom: 1rem;
    }

    /* Suggestion chips */
    .chip {
        display: inline-block;
        padding: 8px 16px;
        margin: 4px;
        border-radius: 20px;
        background: #1E1E1E;
        border: 1px solid #E53935;
        color: #FAFAFA;
        cursor: pointer;
        font-size: 0.85rem;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []
if "remaining_quota" not in st.session_state:
    st.session_state.remaining_quota = None

# ---------------------------------------------------------------------------
# Fetch current quota
# ---------------------------------------------------------------------------


def fetch_quota():
    try:
        r = httpx.get(f"{API_BASE}/usage/{USER_ID}", timeout=5)
        if r.status_code == 200:
            data = r.json()
            st.session_state.remaining_quota = data["remaining"]
            return data
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Hero section
# ---------------------------------------------------------------------------

if not st.session_state.messages:
    st.markdown('<div class="hero-title">🎩 ดอนฮวน</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="hero-subtitle">Self-esteem › Looks › Money › Technique</div>',
        unsafe_allow_html=True,
    )

    # Fetch and show quota
    quota_data = fetch_quota()
    if quota_data:
        st.markdown(
            f'<div class="quota-badge">เหลือ {quota_data["remaining"]}/{quota_data["daily_limit"]} คำถามวันนี้</div>',
            unsafe_allow_html=True,
        )

    # Suggestion chips
    st.markdown("#### ลองถามเรื่องเหล่านี้:")
    suggestions = [
        "ผมชอบสาวคนนึงแต่ไม่กล้าเข้าไปคุย",
        "เธอบอกว่าเราเป็นแค่เพื่อนกัน",
        "ผมดีกับเธอมากแต่เธอไม่สนใจ",
        "วิธีสร้าง self-esteem ทำยังไง",
    ]
    cols = st.columns(2)
    for i, suggestion in enumerate(suggestions):
        if cols[i % 2].button(suggestion, key=f"sug_{i}"):
            st.session_state.messages.append({"role": "user", "content": suggestion})
            st.rerun()

# ---------------------------------------------------------------------------
# Chat history display
# ---------------------------------------------------------------------------

for msg in st.session_state.messages:
    avatar = "🎩" if msg["role"] == "assistant" else "🙋‍♂️"
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

# ---------------------------------------------------------------------------
# Chat input
# ---------------------------------------------------------------------------

if prompt := st.chat_input("ถาม DJ ได้เลย..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="🙋‍♂️"):
        st.markdown(prompt)

    # Call FastAPI backend
    with st.chat_message("assistant", avatar="🎩"):
        with st.spinner("DJ กำลังคิด..."):
            try:
                r = httpx.post(
                    f"{API_BASE}/chat",
                    json={"user_id": USER_ID, "message": prompt},
                    timeout=30,
                )
                if r.status_code == 200:
                    data = r.json()
                    response_text = data["response"]
                    st.session_state.remaining_quota = data["remaining_quota"]
                else:
                    response_text = f"Error: {r.status_code} — {r.text}"
            except httpx.ConnectError:
                response_text = "ไม่สามารถเชื่อมต่อ API server ได้ — กรุณาเปิด FastAPI server ก่อน"
            except Exception as e:
                response_text = f"Error: {e}"

        st.markdown(response_text)

    st.session_state.messages.append({"role": "assistant", "content": response_text})

# ---------------------------------------------------------------------------
# Sidebar info
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("---")
    st.markdown("### 📊 Usage")
    if st.session_state.remaining_quota is not None:
        st.metric("Remaining today", f"{st.session_state.remaining_quota}")
    if st.button("🔄 Refresh quota"):
        fetch_quota()
        st.rerun()

    st.markdown("---")
    st.markdown("### ℹ️ About")
    st.markdown("""
    **DJ Agent v2** — ดอนฮวน dating coach
    - Model: gpt-4o-mini
    - Framework: Microsoft Agent Framework
    - 33 ทฤษฎี + 15 เทคนิค + 6 red flags
    """)
