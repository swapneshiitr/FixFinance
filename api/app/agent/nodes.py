"""Interview agent nodes + routers (LLD §5.2, §5.3).

The graph owns control flow; the LLM mechanics live behind the gateway. Nodes are
async because the gateway calls are async (so the graph runs via `ainvoke` with an
async checkpointer).

Node responsibilities:
  - greet      — static warm intro, no LLM (saves a call); seeds coverage so the
                 first question is informed.
  - extract    — gateway.call_structured → merge a PartialProforma delta into draft,
                 never overwriting a user_edited field.
  - update_coverage — deterministic recompute (no LLM).
  - ask        — gateway.call_text → the next single question.
  - confirm    — gateway.call_text → summary + invitation to correct/add.
"""
from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from app.agent import coverage as cov
from app.agent.state import InterviewState
from app.orchestration import gateway
from app.schemas.proforma import LIST_FIELDS, SCALAR_FIELDS, ExtractedFacts

log = logging.getLogger("fixfinance.agent")

TRANSCRIPT_TAIL_N = 6  # OQ-L2: start at 6, tune via traces

# Static, non-LLM greeting (not a prompt template, so inlining is fine — FR4.2
# governs LLM prompts, which must be versioned files).
GREETING = (
    "Hi! I'm FixFinance, your personal-finance consultant. I'll ask a few quick "
    "questions about your income, savings, and goals so I can put together a clear "
    "picture of your finances. There are no wrong answers — rough numbers are fine, "
    "and you can always correct anything later. Let's begin."
)

# When the model emits a value but no confidence entry, assume a moderate-high
# confidence (it chose to emit it). Tunable knob — see LEARNINGS "taste the soup".
_DEFAULT_CONFIDENCE = 0.7
_LIST_FIELDS = set(LIST_FIELDS)
_SCALAR_FIELDS = set(SCALAR_FIELDS)


def transcript_tail(messages: list, n: int = TRANSCRIPT_TAIL_N) -> str:
    """Render the last `n` messages as `role: text` lines for a prompt."""
    lines = []
    for m in messages[-n:]:
        role = "user" if getattr(m, "type", "") == "human" else "assistant"
        lines.append(f"{role}: {m.content}")
    return "\n".join(lines)


def _flatten_draft(draft: dict) -> dict:
    """Flat {field: value} view of the draft for the extract PROMPT.

    Critical: the model must see plain values, not the `Field{value,source,confidence}`
    wrapper — otherwise it mimics that shape for newly-extracted fields, which then fail
    the flat `ExtractedFacts` schema and stall extraction. (The stored draft stays wrapped.)
    """
    flat = {}
    for key, v in draft.items():
        flat[key] = v.get("value") if isinstance(v, dict) and "value" in v else v
    return flat


def _apply_extraction(draft: dict, facts: ExtractedFacts) -> dict:
    """Map a flat `ExtractedFacts` delta into the Field-wrapped draft.

    Scalars get wrapped as `{value, source: ai_extracted, confidence}` using the
    model's `confidence` map; a `user_edited` scalar is never overwritten. List
    fields replace wholesale (the agent only re-probes a list while it's `None`).
    """
    merged = dict(draft)
    data = facts.model_dump(exclude_none=True)
    conf = data.pop("confidence", {}) or {}
    for key, value in data.items():
        if key in _LIST_FIELDS:
            merged[key] = value  # list of dicts (SIP/FD/… dumped)
        elif key in _SCALAR_FIELDS:
            existing = merged.get(key)
            if existing and existing.get("source") == "user_edited":
                continue  # never overwrite a human edit
            merged[key] = {
                "value": value,
                "source": "ai_extracted",
                "confidence": float(conf.get(key, _DEFAULT_CONFIDENCE)),
            }
    return merged


# --- Nodes ------------------------------------------------------------------


async def greet_node(state: InterviewState) -> dict:
    return {
        "messages": [AIMessage(content=GREETING)],
        "phase": "interviewing",
        # seed coverage from the empty draft so `ask` knows every field is a gap
        "coverage": cov.compute_coverage(state.get("draft", {})),
    }


async def extract_node(state: InterviewState) -> dict:
    draft = state.get("draft", {})
    tail = transcript_tail(state["messages"])
    try:
        facts = await gateway.call_structured(
            "extract_facts", "v1", {"draft": _flatten_draft(draft), "transcript_tail": tail}, ExtractedFacts
        )
        captured = [k for k in facts.model_dump(exclude_none=True) if k != "confidence"]
        draft = _apply_extraction(draft, facts)
        # Observability (the blind spot): log field NAMES captured this turn — never values.
        log.info("extract turn=%d captured=%s", state.get("turn_count", 0) + 1, captured)
    except gateway.GatewayError:
        # Degrade gracefully: keep the prior draft, let the next question re-probe.
        log.warning("extraction failed this turn; draft unchanged", exc_info=True)
    return {"draft": draft, "turn_count": state.get("turn_count", 0) + 1}


async def coverage_node(state: InterviewState) -> dict:
    coverage = cov.compute_coverage(state.get("draft", {}))
    log.info("coverage pct=%d next_target=%s gaps=%s",
             cov.coverage_pct(coverage), cov.next_target(coverage), list(cov.gaps(coverage)))
    return {"coverage": coverage}


async def ask_node(state: InterviewState) -> dict:
    coverage = state.get("coverage", {})
    target = cov.next_target(coverage)
    text = await gateway.call_text(
        "interview_ask",
        "v1",
        {
            "target": cov.FIELD_LABELS.get(target, "any remaining detail") if target else "any remaining detail",
            "known": cov.known_labels(coverage) or "(nothing yet)",
            "transcript_tail": transcript_tail(state["messages"]),
        },
    )
    return {"messages": [AIMessage(content=text)]}


async def confirm_node(state: InterviewState) -> dict:
    text = await gateway.call_text(
        "interview_confirm",
        "v1",
        {
            "draft": state.get("draft", {}),
            "transcript_tail": transcript_tail(state["messages"]),
        },
    )
    return {"messages": [AIMessage(content=text)], "phase": "confirming"}


# --- Routers ----------------------------------------------------------------


def entry_router(state: InterviewState) -> str:
    """First invoke (phase still 'greeting') greets; every later turn extracts."""
    return "greet" if state.get("phase", "greeting") == "greeting" else "extract"


def route(state: InterviewState) -> str:
    """Enough learned → confirm; otherwise ask the next question."""
    return "confirm" if cov.is_sufficient(state.get("coverage", {})) else "ask"
