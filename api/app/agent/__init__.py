"""The interview agent (LangGraph) — SG1, stateful orchestration (HLD §6, LLD §5).

A checkpointed state graph drives the interview's *control flow*
(`entry_router → greet|extract → update_coverage → route → ask|confirm → END`),
while every LLM call inside a node still goes through the orchestration gateway.

Pause = end the run. The next user turn re-invokes from `entry_router` and resumes
from the Postgres checkpoint — there is no long-lived `interrupt`. State is loaded,
not execution position.
"""
