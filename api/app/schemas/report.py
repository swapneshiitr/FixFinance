"""Report schemas (LLD §11.4) — the structured output of report synthesis (OQ-H3).

`ReportContent` is what the gateway forces the LLM to emit (and what we persist as
`reports.content` JSONB). Sources are re-attached deterministically from the RAG
pool after generation, so citations are always authentic (never hallucinated).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator

Severity = Literal["good", "watch", "act"]

_PRIORITY_ALIASES = {"medium": "med", "moderate": "med", "mid": "med", "urgent": "high", "critical": "high"}
_RATING_ALIASES = {"ok": "good", "fine": "good", "caution": "watch", "action": "act", "action_needed": "act"}


def _unwrap(v):
    """Tolerate smaller models wrapping an enum as {"value": x} / {"type": x} / etc."""
    if isinstance(v, dict):
        for k in ("value", "type", "rating", "priority", "severity", "name", "label"):
            if isinstance(v.get(k), str):
                return v[k]
        strs = [x for x in v.values() if isinstance(x, str)]
        if len(strs) == 1:
            return strs[0]
    return v


class Recommendation(BaseModel):
    # Kept as plain str (not Literal) so the model isn't asked to satisfy a JSON-schema
    # enum it tends to wrap; the validator normalizes + defaults to a safe value.
    priority: str = "med"
    action: str
    rationale: str
    principle_id: str  # must be one of the provided principles
    sources: list[dict] = []  # [{title, url}] — canonicalized from the RAG pool post-synthesis
    user_figures: dict = {}  # e.g. {"emergency_fund_months": 1.2}

    @field_validator("priority", mode="before")
    @classmethod
    def _norm_priority(cls, v):
        v = _unwrap(v)
        if isinstance(v, str):
            v = _PRIORITY_ALIASES.get(v.strip().lower(), v.strip().lower())
        return v if v in ("high", "med", "low") else "med"


class Rating(BaseModel):
    dimension: str  # emergency_fund | savings_rate | insurance | ...
    rating: str  # normalized to good|watch|act; authoritative ratings are set from findings
    value: float | str | None = None

    @field_validator("rating", mode="before")
    @classmethod
    def _norm_rating(cls, v):
        v = _unwrap(v)
        if isinstance(v, str):
            v = _RATING_ALIASES.get(v.strip().lower(), v.strip().lower())
        return v if v in ("good", "watch", "act") else "watch"


class ReportContent(BaseModel):
    snapshot: dict  # headline metrics in plain language
    ratings: list[Rating]
    findings: list[str]
    recommendations: list[Recommendation]
    disclaimer: str
