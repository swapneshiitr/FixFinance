"""Prompt registry (LLD §7).

Prompts are **versioned files** under `prompts/<name>/<version>.md` — never inline
strings (FR4.2). Changing behavior means a new version file, so every trace ties a
result back to the exact prompt text that produced it.

File format — YAML frontmatter, then a `[SYSTEM]` and a `[USER]` block:

    ---
    name: extract_facts
    version: v1
    description: ...
    ---
    [SYSTEM]
    ...system text with ${placeholders}...

    [USER]
    ...user text with ${placeholders}...

Placeholders use `${name}` (`string.Template`), NOT `{name}`, so prompt bodies can
contain literal JSON braces (e.g. example payloads) without escaping. Inputs that
aren't already strings are JSON-serialized before substitution.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from string import Template

import yaml

PROMPTS_DIR = Path(__file__).parent / "prompts"

_SYSTEM_MARKER = "[SYSTEM]"
_USER_MARKER = "[USER]"


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: str
    meta: dict
    system: str
    user: str

    def render(self, inputs: dict | None = None) -> tuple[str, str]:
        """Return (system, user) with ${placeholders} substituted.

        Missing placeholders are left intact (`safe_substitute`) rather than
        raising — a partially-rendered prompt surfaces in traces far more
        usefully than a KeyError swallowing the whole call.
        """
        mapping = {k: _stringify(v) for k, v in (inputs or {}).items()}
        return (
            Template(self.system).safe_substitute(mapping),
            Template(self.user).safe_substitute(mapping),
        )


def _stringify(v: object) -> str:
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False, default=str, indent=2)


def _parse(text: str, name: str, version: str) -> PromptTemplate:
    if not text.startswith("---"):
        raise ValueError(f"prompt {name}/{version}: missing YAML frontmatter")
    _, frontmatter, body = text.split("---", 2)
    meta = yaml.safe_load(frontmatter) or {}

    if _SYSTEM_MARKER not in body or _USER_MARKER not in body:
        raise ValueError(
            f"prompt {name}/{version}: must contain {_SYSTEM_MARKER} and {_USER_MARKER} blocks"
        )
    system_part, user_part = body.split(_USER_MARKER, 1)
    system = system_part.split(_SYSTEM_MARKER, 1)[1].strip()
    user = user_part.strip()
    return PromptTemplate(name=name, version=version, meta=meta, system=system, user=user)


_cache: dict[tuple[str, str], PromptTemplate] = {}


def get(name: str, version: str) -> PromptTemplate:
    """Load (and cache) the template for `(name, version)`."""
    key = (name, version)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    path = PROMPTS_DIR / name / f"{version}.md"
    if not path.is_file():
        raise FileNotFoundError(f"prompt not found: {path}")
    template = _parse(path.read_text(encoding="utf-8"), name, version)
    _cache[key] = template
    return template
