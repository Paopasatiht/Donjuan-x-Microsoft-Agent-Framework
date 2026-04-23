"""Tests for DJ knowledge base."""

from dj_agent.knowledge import (
    DJ_SYSTEM_PROMPT,
    RED_FLAGS,
    TECHNIQUES,
    THEORIES,
    build_knowledge_texts,
)


def test_theories_count():
    assert len(THEORIES) == 33


def test_techniques_count():
    assert len(TECHNIQUES) == 15


def test_red_flags_count():
    assert len(RED_FLAGS) == 6


def test_build_knowledge_texts():
    docs = build_knowledge_texts()
    assert len(docs) == 54  # 33 + 15 + 6
    assert all("text" in d and "type" in d and "title" in d for d in docs)


def test_system_prompt_contains_key_elements():
    assert "ดอนฮวน" in DJ_SYSTEM_PROMPT
    assert "DIAGNOSE" in DJ_SYSTEM_PROMPT
    assert "retrieve_dj_knowledge" in DJ_SYSTEM_PROMPT
    assert "Hard limits" in DJ_SYSTEM_PROMPT
