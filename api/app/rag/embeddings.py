"""Embeddings (LLD §10.3) — provider-agnostic behind a single `embed()`.

Default `ollama` (`nomic-embed-text`, 768-dim) is called through the same
OpenAI-compatible API as the LLM; `gemini`/`openai` work the same way; `local`
lazy-loads `sentence-transformers`. The returned vector dim MUST equal
`settings.embeddings_dim` and the `VECTOR(...)` column (§3).
"""
from __future__ import annotations

from openai import AsyncOpenAI

from app.config import settings

_client: AsyncOpenAI | None = None
_local_model = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key or "x")
    return _client


def to_pgvector(vec: list[float]) -> str:
    """pgvector text literal, e.g. '[0.1,0.2,...]', for CAST(:v AS vector)."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


async def embed(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts → one vector each (order preserved)."""
    if not texts:
        return []
    if settings.embeddings_provider == "local":
        return _embed_local(texts)
    resp = await _get_client().embeddings.create(model=settings.embeddings_model, input=texts)
    return [d.embedding for d in resp.data]


def _embed_local(texts: list[str]) -> list[list[float]]:
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer  # lazy: heavy, optional

        _local_model = SentenceTransformer(settings.embeddings_model)
    return [v.tolist() for v in _local_model.encode(texts, normalize_embeddings=True)]
