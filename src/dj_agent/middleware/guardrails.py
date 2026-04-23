"""AgentMiddleware that blocks harmful content."""

import logging
from collections.abc import Awaitable, Callable

from agent_framework import AgentContext, AgentMiddleware, AgentResponse, Message

logger = logging.getLogger(__name__)

# Thai keywords related to manipulation, coercion, harm
BLOCKED_PATTERNS = [
    "วิธีบังคับ",
    "หลอกให้",
    "ทำให้เธอต้อง",
    "วิธีข่มขืน",
    "มอมเหล้า",
    "ยาปลุกเซ็กส์",
    "วิธีแก้แค้น",
    "ทำร้าย",
]


class GuardrailsMiddleware(AgentMiddleware):
    """Block requests containing harmful or manipulative content."""

    def __init__(self, blocked_patterns: list[str] | None = None) -> None:
        self.blocked_patterns = blocked_patterns or BLOCKED_PATTERNS

    async def process(
        self,
        context: AgentContext,
        call_next: Callable[[], Awaitable[None]],
    ) -> None:
        last_message = context.messages[-1] if context.messages else None
        if last_message and last_message.text:
            text_lower = last_message.text.lower()
            for pattern in self.blocked_patterns:
                if pattern in text_lower:
                    logger.warning(f"Guardrail triggered: blocked pattern '{pattern}'")
                    context.terminate = True
                    context.result = AgentResponse(
                        messages=[
                            Message(
                                role="assistant",
                                contents=["DJ ดึงดูด ไม่บังคับ — ผมช่วยเรื่องนี้ไม่ได้ Consent คือเด็ดขาด"],
                            )
                        ]
                    )
                    return

        await call_next()
