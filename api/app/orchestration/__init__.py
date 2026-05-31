"""LLM Orchestration — the ONLY path to Claude (HLD §7, LLD §6).

No service calls `anthropic.messages.create()` directly. This package owns:
  - prompt resolution (versioned files, `registry`),
  - forced-tool structured output + Pydantic re-validation (`gateway`),
  - the bounded repair loop (`gateway`), and
  - one trace row per call (`tracing` → `llm_calls`).

This single chokepoint is what makes the system observable and is the strongest
platform-engineering signal in the project.
"""
