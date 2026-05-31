"""Retriever (LLD §10.4) — pgvector cosine search over principle chunks.

Returns each matched principle's statement + `sources[]` (and `what_to_check`)
so the report synthesis can ground a recommendation AND cite an authentic source.
"""
from __future__ import annotations

import json

from sqlalchemy import text

from app.db import SessionLocal
from app.rag import embeddings

_SQL = text(
    """
    SELECT p.id, p.statement, p.rule_of_thumb, p.what_to_check, p.sources,
           1 - (c.embedding <=> CAST(:q AS vector)) AS score
    FROM principle_chunks c
    JOIN principles p ON p.id = c.principle_id
    ORDER BY c.embedding <=> CAST(:q AS vector)
    LIMIT :k
    """
)


async def retrieve(query: str, k: int = 4) -> list[dict]:
    """Top-k principles for a query, by cosine similarity."""
    qvec = (await embeddings.embed([query]))[0]
    async with SessionLocal() as session:
        rows = (
            await session.execute(_SQL, {"q": embeddings.to_pgvector(qvec), "k": k})
        ).mappings().all()

    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("sources"), str):  # raw text() query: JSONB may arrive as str
            d["sources"] = json.loads(d["sources"])
        d["score"] = round(float(d["score"]), 4)
        out.append(d)
    return out


_BY_IDS_SQL = text(
    "SELECT id, statement, rule_of_thumb, what_to_check, sources FROM principles WHERE id = ANY(:ids)"
)


async def get_by_ids(ids: list[str]) -> list[dict]:
    """Fetch specific principles by id (guarantees a finding's own principle is citable)."""
    if not ids:
        return []
    async with SessionLocal() as session:
        rows = (await session.execute(_BY_IDS_SQL, {"ids": list(ids)})).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("sources"), str):
            d["sources"] = json.loads(d["sources"])
        out.append(d)
    return out
