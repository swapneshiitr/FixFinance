"""Interview agent state (LLD §5.1).

`messages` uses LangGraph's `add_messages` reducer so node returns *append* to the
transcript rather than replace it. The remaining channels are plain values that a
node return overwrites. The whole dict is what `PostgresSaver` checkpoints each
node — which is what makes resume-for-free work (FR1.3).
"""
from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class InterviewState(TypedDict):
    messages: Annotated[list, add_messages]  # LangChain message objects
    draft: dict  # PartialProforma as a dict (the None-vs-[] convention lives here)
    coverage: dict[str, str]  # field -> unknown | low_confidence | known
    turn_count: int
    phase: str  # greeting | interviewing | confirming | done


def initial_state() -> InterviewState:
    """The state a brand-new interview session starts from."""
    return {
        "messages": [],
        "draft": {},
        "coverage": {},
        "turn_count": 0,
        "phase": "greeting",
    }
