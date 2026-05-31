"""Coverage & sufficiency (LLD §5.4) — resolves OQ-H1.

Deterministic, rule-based, NO LLM (cheaper, testable, predictable). Decides when
the interview has learned enough to move from asking → confirming.

The None-vs-`[]` convention is load-bearing here: for a list field, `None` means
"not yet probed" (still a gap) while `[]` means "asked, user has none" (satisfied).
"""
from __future__ import annotations

REQUIRED = [  # scalar Field[T] values that must be known
    "age",
    "tax_regime",
    "monthly_take_home",
    "epf_monthly",
    "fixed_household_monthly",
    "health_insurance_cover",
    "term_life_cover",
    "emergency_fund",
    "risk_appetite",
]
PROBES = ["sips", "fds"]  # list fields that must be probed (None→not asked; []→asked, none)

# Below this, an ai_extracted value is treated as not-yet-confirmed and re-probed.
# A runtime knob ("taste the soup"), not a contract — tune via traces/evals.
CONFIDENCE_THRESHOLD = 0.6


def field_status(draft: dict, key: str) -> str:
    """Status of a scalar provenance-wrapped field."""
    f = draft.get(key)
    if not f or f.get("value") is None:
        return "unknown"
    if f.get("source") == "ai_extracted" and f.get("confidence", 0) < CONFIDENCE_THRESHOLD:
        return "low_confidence"
    return "known"


def probe_status(draft: dict, key: str) -> str:
    """Status of a list field — `[]` counts as known ("asked, none")."""
    return "unknown" if draft.get(key) is None else "known"


def compute_coverage(draft: dict) -> dict[str, str]:
    """Recompute the coverage map from the current draft."""
    coverage = {k: field_status(draft, k) for k in REQUIRED}
    coverage.update({k: probe_status(draft, k) for k in PROBES})
    return coverage


def is_sufficient(coverage: dict[str, str]) -> bool:
    """True once every REQUIRED scalar and every PROBE list is `known`."""
    keys = REQUIRED + PROBES
    return all(coverage.get(k) == "known" for k in keys)


def coverage_pct(coverage: dict[str, str]) -> int:
    keys = REQUIRED + PROBES
    known = sum(1 for k in keys if coverage.get(k) == "known")
    return round(100 * known / len(keys))


def gaps(coverage: dict[str, str]) -> dict[str, str]:
    """The not-yet-known fields (what the ask node should target)."""
    return {k: v for k, v in coverage.items() if v != "known"}


# Foundational → detail. The ask node walks this and asks ONE field at a time, so
# the *routing* is deterministic (Python) while the LLM only phrases the question.
ASK_ORDER = [
    "age", "monthly_take_home", "fixed_household_monthly", "epf_monthly",
    "sips", "fds", "emergency_fund", "health_insurance_cover", "term_life_cover",
    "tax_regime", "risk_appetite",
]

# Plain-language hint per field, handed to the ask prompt.
FIELD_LABELS = {
    "age": "their age",
    "monthly_take_home": "their monthly take-home pay (after taxes and deductions)",
    "fixed_household_monthly": "their typical fixed monthly household expenses (rent, bills, groceries, EMIs)",
    "epf_monthly": "their own monthly EPF contribution (the employee share only)",
    "sips": "whether they invest via SIPs in mutual funds and how much per month (or none)",
    "fds": "whether they hold any fixed deposits and roughly how much (or none)",
    "emergency_fund": "how much they keep as an emergency fund / liquid buffer (0 if none)",
    "health_insurance_cover": "their health insurance cover amount, including any employer cover (0 if none)",
    "term_life_cover": "their term life insurance cover amount (0 if none)",
    "tax_regime": "whether they are on the old or new income-tax regime",
    "risk_appetite": "their comfort with investment risk — low, medium, or high",
}


def next_target(coverage: dict[str, str]) -> str | None:
    """The single highest-priority not-yet-known field to ask about (None if done)."""
    for key in ASK_ORDER:
        if coverage.get(key, "unknown") != "known":
            return key
    return None


def known_labels(coverage: dict[str, str]) -> list[str]:
    """Plain-language labels of fields already captured (so the ask node won't re-ask)."""
    return [FIELD_LABELS.get(k, k) for k in ASK_ORDER if coverage.get(k) == "known"]
