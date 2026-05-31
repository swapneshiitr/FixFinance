"""LLM Orchestration Gateway (LLD §6) — the ONLY path to the LLM.

Provider-agnostic: it speaks to any **OpenAI-compatible** endpoint (Gemini by
default, or Ollama / Groq / OpenAI) via the OpenAI SDK with a configurable
`base_url`. Swapping models is a `.env` change, not a code change — which is the
whole point of having one chokepoint.

Two entry points:
  - `call_text`       → free-form assistant prose (the interview's questions).
  - `call_structured` → forced-tool JSON, re-validated against a Pydantic schema,
                        with a bounded repair loop.

Why a gateway at all (the platform-engineering signal): every call is funnelled
through one place that resolves a *versioned* prompt, pins structured output to a
tool schema, re-validates with Pydantic (belt + suspenders), repairs on validation
failure up to a bounded budget, and emits exactly one trace row. Nothing else in
the codebase imports an LLM SDK.
"""
from __future__ import annotations

import json
import time

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.orchestration import registry, tracing

_TOOL_NAME = "emit"

_client: AsyncOpenAI | None = None


class GatewayError(RuntimeError):
    """Raised when the gateway cannot produce a valid result.

    Callers degrade gracefully (e.g. flag affected fields `needs_review`)
    rather than crashing the interview turn.
    """


def _get_client() -> AsyncOpenAI:
    """Lazily construct the OpenAI-compatible client (so importing needs no key)."""
    global _client
    if _client is None:
        if not settings.llm_api_key:
            raise GatewayError("LLM_API_KEY is not configured")
        _client = AsyncOpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
    return _client


def _now_ms() -> float:
    return time.monotonic() * 1000.0


def _usage(resp) -> tuple[int, int]:
    u = getattr(resp, "usage", None)
    if u is None:
        return 0, 0
    return getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0


def _first_tool_call(message):
    calls = getattr(message, "tool_calls", None)
    return calls[0] if calls else None


def _strip_titles(obj):
    """Drop Pydantic's `title` keys from a JSON schema.

    Smaller models (e.g. qwen2.5:7b) tend to echo `title` back into their output —
    e.g. emitting `{"title": "Rating", "value": "act"}` where a bare enum was wanted.
    Titles are descriptive-only, so removing them yields cleaner tool calls.
    """
    if isinstance(obj, dict):
        return {k: _strip_titles(v) for k, v in obj.items() if k != "title"}
    if isinstance(obj, list):
        return [_strip_titles(x) for x in obj]
    return obj


async def call_text(
    prompt_name: str,
    version: str,
    inputs: dict | None = None,
    *,
    session_id: str | None = None,
    model: str | None = None,
    max_tokens: int = 1024,
    temperature: float | None = None,
) -> str:
    """Render `(prompt_name, version)`, call the LLM, return the assistant text."""
    model = model or settings.model_main
    temperature = settings.temperature_text if temperature is None else temperature
    template = registry.get(prompt_name, version)
    system, user = template.render(inputs)

    started = _now_ms()
    try:
        resp = await _get_client().chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
    except Exception as exc:  # noqa: BLE001 — trace the failure, then surface it
        await tracing.trace(
            prompt_name=prompt_name, prompt_version=version, model=model,
            outcome="error", latency_ms=int(_now_ms() - started), session_id=session_id,
        )
        raise GatewayError(f"text call failed: {exc}") from exc

    tokens_in, tokens_out = _usage(resp)
    await tracing.trace(
        prompt_name=prompt_name, prompt_version=version, model=model, outcome="success",
        tokens_in=tokens_in, tokens_out=tokens_out,
        latency_ms=int(_now_ms() - started), session_id=session_id,
    )
    return resp.choices[0].message.content or ""


async def call_structured(
    prompt_name: str,
    version: str,
    inputs: dict | None,
    schema: type[BaseModel],
    *,
    session_id: str | None = None,
    max_repair: int | None = None,
    model: str | None = None,
    max_tokens: int = 2048,
    temperature: float | None = None,
) -> BaseModel:
    """Forced-tool structured extraction with bounded Pydantic-repair (LLD §6).

    The model is pinned to the `emit` tool whose parameter schema is the Pydantic
    model's JSON schema, so it *must* return matching JSON. We still re-validate;
    on a JSON/validation error we feed the errors back as a `tool` message and
    retry, up to `max_repair` times. Tokens/latency are summed into one trace.
    """
    model = model or settings.model_main
    max_repair = settings.max_repair if max_repair is None else max_repair
    temperature = settings.temperature_structured if temperature is None else temperature
    template = registry.get(prompt_name, version)
    system, user = template.render(inputs)

    tool = {
        "type": "function",
        "function": {
            "name": _TOOL_NAME,
            "description": f"Emit a {schema.__name__} as structured JSON.",
            "parameters": _strip_titles(schema.model_json_schema()),
        },
    }
    convo: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    tokens_in = tokens_out = 0
    started = _now_ms()
    attempt = 0  # also the count of repairs done so far (0 = initial attempt)
    last_error: Exception | None = None

    for attempt in range(1 + max_repair):
        try:
            resp = await _get_client().chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=convo,
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": _TOOL_NAME}},
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            await tracing.trace(
                prompt_name=prompt_name, prompt_version=version, model=model,
                outcome="error", retries=attempt, tokens_in=tokens_in, tokens_out=tokens_out,
                latency_ms=int(_now_ms() - started), session_id=session_id,
            )
            raise GatewayError(f"structured call failed: {exc}") from exc

        ti, to = _usage(resp)
        tokens_in += ti
        tokens_out += to

        message = resp.choices[0].message
        tool_call = _first_tool_call(message)
        if tool_call is None:
            # Some providers occasionally answer in text despite tool_choice.
            # Treat as repairable: nudge and retry within the budget.
            last_error = GatewayError("model did not call the emit tool")
            if attempt < max_repair:
                convo.append({"role": "assistant", "content": message.content or ""})
                convo.append({
                    "role": "user",
                    "content": f"You must call the `{_TOOL_NAME}` function with the extracted JSON. Do not reply in plain text.",
                })
                continue
            break

        try:
            raw = json.loads(tool_call.function.arguments)
            obj = schema.model_validate(raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            if attempt < max_repair:
                # Echo the assistant tool call, then return the error as a tool
                # message so the model can self-correct (OpenAI tool protocol).
                convo.append({
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [{
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    }],
                })
                convo.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": f"Validation errors:\n{exc}\nRe-emit valid JSON matching the schema.",
                })
                continue
            break  # repair budget exhausted

        await tracing.trace(
            prompt_name=prompt_name, prompt_version=version, model=model,
            outcome="success" if attempt == 0 else "repaired", retries=attempt,
            tokens_in=tokens_in, tokens_out=tokens_out,
            latency_ms=int(_now_ms() - started), session_id=session_id,
        )
        return obj

    # Fell through: never produced a valid object within the repair budget.
    await tracing.trace(
        prompt_name=prompt_name, prompt_version=version, model=model,
        outcome="validation_failed", retries=attempt,
        tokens_in=tokens_in, tokens_out=tokens_out,
        latency_ms=int(_now_ms() - started), session_id=session_id,
    )
    raise GatewayError(f"structured output failed validation after {attempt} repair(s): {last_error}")
