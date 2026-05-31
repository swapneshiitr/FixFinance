"""Eval harness (LLD §14, SG4) — the regression guard for prompt/threshold changes.

Loads YAML fixtures, runs the REAL extract/report paths, checks assertions, prints a
pass/fail table, writes results.json, and exits non-zero if anything fails.

Run:  PYTHONPATH=. python evals/run_evals.py        (needs Postgres + Ollama up)
Assertion types: equals, approx (±tol), report_mentions, report_cites_source,
rating {dimension, equals}, and llm_judge {rubric, threshold} (uses MODEL_JUDGE).
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel

from app.config import settings
from app.orchestration import gateway
from app.schemas.proforma import LIST_FIELDS, ExtractedFacts
from app.services import proforma_service, report_service

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
RESULTS_PATH = Path(__file__).resolve().parent / "results.json"


class JudgeVerdict(BaseModel):
    score: float
    reason: str = ""


# --- path resolution over the extracted draft --------------------------------


def _resolve(obj, path: str):
    tokens: list = []
    for part in path.split("."):
        key = re.match(r"^[^\[]+", part).group(0)
        tokens.append(key)
        tokens.extend(int(i) for i in re.findall(r"\[(\d+)\]", part))
    cur = obj
    for t in tokens:
        cur = cur[t]
    # unwrap a Field-wrapped scalar
    if isinstance(cur, dict) and "value" in cur and set(cur) <= {"value", "source", "confidence"}:
        return cur["value"]
    return cur


# --- runners -----------------------------------------------------------------


async def run_extraction(fx: dict):
    facts = await gateway.call_structured(
        "extract_facts", "v1", {"draft": {}, "transcript_tail": fx["transcript"]}, ExtractedFacts
    )
    from app.agent.nodes import _apply_extraction

    return _apply_extraction({}, facts)


def _wrap_proforma(pf: dict) -> dict:
    data = {}
    for k, v in pf.items():
        data[k] = v if k in LIST_FIELDS else {"value": v, "source": "ai_extracted", "confidence": 1.0}
    return data


async def run_report(fx: dict) -> dict:
    data = _wrap_proforma(fx["proforma"])
    derived = proforma_service.compute_derived(data)
    return await report_service.build_report_content(data, derived)


def _report_text(content: dict) -> str:
    parts = [json.dumps(content.get("snapshot", {}))]
    parts += content.get("findings", [])
    for r in content.get("recommendations", []):
        parts += [r.get("action", ""), r.get("rationale", "")]
    return " ".join(parts).lower()


# --- assertion checking ------------------------------------------------------


async def check(kind: str, result, a: dict) -> tuple[bool, str]:
    try:
        if "equals" in a and "path" in a:
            got = _resolve(result, a["path"])
            return got == a["equals"], f"{a['path']}={got!r} (want {a['equals']!r})"
        if "approx" in a and "path" in a:
            got = _resolve(result, a["path"])
            tol = a.get("tol", 0)
            return abs(float(got) - float(a["approx"])) <= tol, f"{a['path']}={got} (~{a['approx']}±{tol})"
        if "report_mentions" in a:
            needle = a["report_mentions"].lower()
            return needle in _report_text(result), f"mentions {a['report_mentions']!r}"
        if "report_cites_source" in a:
            cited = any(r.get("sources") for r in result.get("recommendations", []))
            return cited == a["report_cites_source"], f"cites_source={cited}"
        if "rating" in a:
            spec = a["rating"]
            match = next((r for r in result.get("ratings", []) if r["dimension"] == spec["dimension"]), None)
            got = match["rating"] if match else None
            return got == spec["equals"], f"rating[{spec['dimension']}]={got} (want {spec['equals']})"
        if "llm_judge" in a:
            spec = a["llm_judge"]
            v: JudgeVerdict = await gateway.call_structured(
                "eval_judge", "v1", {"rubric": spec["rubric"], "output": json.dumps(result)},
                JudgeVerdict, model=settings.model_judge,
            )
            return v.score >= spec["threshold"], f"judge={v.score:.2f}≥{spec['threshold']} — {v.reason[:50]}"
        return False, f"unknown assertion {list(a)}"
    except Exception as e:  # noqa: BLE001
        return False, f"error: {e}"


async def main() -> int:
    fixtures = []
    for f in sorted(FIXTURES_DIR.glob("*.yaml")):
        fixtures += [fx for fx in yaml.safe_load_all(f.read_text()) if fx]

    rows, results = [], []
    print(f"\nRunning {len(fixtures)} eval fixtures against the live stack "
          f"(model={settings.model_main}, judge={settings.model_judge})…\n")

    for fx in fixtures:
        name, kind = fx["name"], fx["kind"]
        try:
            result = await (run_extraction(fx) if kind == "extraction" else run_report(fx))
        except gateway.GatewayError as e:
            for a in fx["expect"]:
                rows.append((name, "run", False, f"path failed: {e}"))
            continue
        for a in fx["expect"]:
            ok, detail = await check(kind, result, a)
            rows.append((name, kind, ok, detail))
            results.append({"fixture": name, "kind": kind, "passed": ok, "detail": detail})

    passed = sum(1 for r in rows if r[2])
    total = len(rows)
    print(f"{'FIXTURE':<26}{'KIND':<12}{'RESULT':<8}DETAIL")
    print("-" * 88)
    for name, kind, ok, detail in rows:
        print(f"{name:<26}{kind:<12}{'PASS' if ok else 'FAIL':<8}{detail}")
    print("-" * 88)
    print(f"\n{passed}/{total} assertions passed\n")

    RESULTS_PATH.write_text(json.dumps(
        {"passed": passed, "total": total, "results": results}, indent=2))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
