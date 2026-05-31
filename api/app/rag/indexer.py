"""Principles indexer (LLD §10.2) — runs at startup, idempotent.

Loads the YAML knowledge base, upserts `principles`, and re-embeds each into
`principle_chunks`. Re-running is safe: principles upsert by id, chunks are
replaced. For the ~8-principle KB this is cheap (a handful of embedding calls).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml
from sqlalchemy import text

from app.db import SessionLocal
from app.rag import embeddings

log = logging.getLogger("fixfinance.rag")

# api/app/rag/indexer.py -> parents[2] == api/ ; knowledge lives at api/knowledge/
PRINCIPLES_DIR = Path(__file__).resolve().parents[2] / "knowledge" / "principles"


def _chunk_text(p: dict) -> str:
    """One retrieval chunk per principle (the KB is small)."""
    return (
        f"{p['statement'].strip()} "
        f"Rule of thumb: {p['rule_of_thumb'].strip()} "
        f"What to check: {p['what_to_check'].strip()}"
    )


def load_principles() -> list[dict]:
    return [yaml.safe_load(f.read_text(encoding="utf-8")) for f in sorted(PRINCIPLES_DIR.glob("*.yaml"))]


async def index_principles() -> int:
    """(Re)index all principle YAMLs into Postgres + pgvector. Returns the count."""
    principles = load_principles()
    if not principles:
        log.warning("no principle YAMLs found at %s", PRINCIPLES_DIR)
        return 0

    chunks = [_chunk_text(p) for p in principles]
    vectors = await embeddings.embed(chunks)

    async with SessionLocal() as session:
        for p, chunk, vec in zip(principles, chunks, vectors):
            await session.execute(
                text(
                    "INSERT INTO principles (id, statement, rule_of_thumb, what_to_check, sources) "
                    "VALUES (:id, :st, :rot, :wtc, CAST(:src AS jsonb)) "
                    "ON CONFLICT (id) DO UPDATE SET statement = EXCLUDED.statement, "
                    "rule_of_thumb = EXCLUDED.rule_of_thumb, what_to_check = EXCLUDED.what_to_check, "
                    "sources = EXCLUDED.sources"
                ),
                {
                    "id": p["id"],
                    "st": p["statement"].strip(),
                    "rot": p["rule_of_thumb"].strip(),
                    "wtc": p["what_to_check"].strip(),
                    "src": json.dumps(p["sources"]),
                },
            )
            await session.execute(
                text("DELETE FROM principle_chunks WHERE principle_id = :id"), {"id": p["id"]}
            )
            await session.execute(
                text(
                    "INSERT INTO principle_chunks (principle_id, chunk_text, embedding) "
                    "VALUES (:id, :txt, CAST(:emb AS vector))"
                ),
                {"id": p["id"], "txt": chunk, "emb": embeddings.to_pgvector(vec)},
            )
        await session.commit()

    log.info("indexed %d principles into pgvector", len(principles))
    return len(principles)
