"""Tests for middleware components."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from dj_agent.middleware.guardrails import GuardrailsMiddleware


@pytest.mark.asyncio
async def test_guardrails_blocks_harmful_content():
    """Guardrails should block messages with harmful patterns."""
    middleware = GuardrailsMiddleware()

    context = MagicMock()
    last_msg = MagicMock()
    last_msg.text = "วิธีบังคับเธอให้ยอม"
    context.messages = [last_msg]
    context.terminate = False

    call_next = AsyncMock()

    await middleware.process(context, call_next)

    assert context.terminate is True
    call_next.assert_not_called()


@pytest.mark.asyncio
async def test_guardrails_allows_normal_content():
    """Guardrails should allow normal coaching questions."""
    middleware = GuardrailsMiddleware()

    context = MagicMock()
    last_msg = MagicMock()
    last_msg.text = "ผม��ยากมั่นใจมากขึ้น ทำยังไงดี"
    context.messages = [last_msg]
    context.terminate = False

    call_next = AsyncMock()

    await middleware.process(context, call_next)

    assert context.terminate is False
    call_next.assert_called_once()
