"""DJ knowledge retrieval tool using OpenAI embeddings + cosine similarity."""

import logging
from typing import Annotated

import numpy as np
from agent_framework import tool
from openai import OpenAI
from pydantic import Field

from .config import settings
from .knowledge import build_knowledge_texts

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory vector store (54 docs — no need for pgvector)
# ---------------------------------------------------------------------------

_knowledge_docs: list[dict] = []
_embeddings: np.ndarray | None = None


def _get_openai_client() -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key)


def init_knowledge_store() -> None:
    """Embed all DJ knowledge documents at startup. Call once."""
    global _knowledge_docs, _embeddings

    _knowledge_docs = build_knowledge_texts()
    texts = [doc["text"] for doc in _knowledge_docs]

    client = _get_openai_client()
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )
    _embeddings = np.array([item.embedding for item in response.data])
    logger.info(f"DJ knowledge store initialized: {len(_knowledge_docs)} documents embedded")


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between vector a and matrix b."""
    norm_a = a / np.linalg.norm(a)
    norm_b = b / np.linalg.norm(b, axis=1, keepdims=True)
    return norm_b @ norm_a


def _search(query: str, k: int = 4) -> list[dict]:
    """Search the knowledge base for the top-k most relevant documents."""
    if _embeddings is None:
        init_knowledge_store()

    client = _get_openai_client()
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=[query],
    )
    query_embedding = np.array(response.data[0].embedding)

    similarities = _cosine_similarity(query_embedding, _embeddings)
    top_indices = np.argsort(similarities)[-k:][::-1]

    results = []
    for idx in top_indices:
        doc = _knowledge_docs[idx]
        results.append({
            "text": doc["text"],
            "type": doc["type"],
            "title": doc["title"],
            "score": float(similarities[idx]),
        })
    return results


# ---------------------------------------------------------------------------
# Agent Framework tool
# ---------------------------------------------------------------------------

@tool
def retrieve_dj_knowledge(
    query: Annotated[str, Field(description="คำค้นหาเกี่ยวกับทฤษฎี DJ, เทคนิค, หรือ red flags เช่น 'กล้าเข้าไปคุย' หรือ 'friendzone'")],
) -> str:
    """ค้นหาทฤษฎี Don Juan 33 ข้อ, เทคนิค DJ, และ red flags ที่เกี่ยวข้องกับคำถามของผู้ใช้"""
    logger.info(f"Retrieving DJ knowledge for: {query}")
    results = _search(query, k=4)

    if not results:
        return "ไม่พบข้อมูลที่ตรงกัน"

    output_parts = []
    for r in results:
        output_parts.append(f"[{r['type']}] {r['title']}: {r['text']} (relevance: {r['score']:.2f})")

    return "\n\n".join(output_parts)
