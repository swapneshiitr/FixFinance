"""The Proforma — THE core contract (LLD §4).

Pydantic is the **single source of truth**. This one model:
  1. validates user edits (the proforma editor PATCHes against it),
  2. persists as JSONB (`proformas.data`), and
  3. its JSON schema is what the gateway hands Claude for forced-tool
     structured extraction (§6).

Every captured value is wrapped in `Field[T]` carrying provenance + confidence,
so the system always knows whether a number came from the LLM, a human edit, or
a derivation — and how much to trust an extracted one (the coverage logic in
§5.4 keys off `confidence < 0.6`).

**`PartialProforma`** is the all-optional mirror used during the interview: it is
the agent's working `draft` and the extraction target. It is *derived* from
`Proforma` (not hand-written) so the two can never drift — drift in the core
contract is exactly the bug we cannot afford.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, create_model, field_validator

Provenance = Literal["ai_extracted", "user_edited", "derived"]


class Field[T](BaseModel):
    """A single captured value plus where it came from and how sure we are.

    `confidence` is only meaningful for `ai_extracted`; user edits and derived
    values are certain by construction.
    """

    value: T | None = None
    source: Provenance = "ai_extracted"
    confidence: float = 0.0  # 0..1

    @field_validator("confidence")
    @classmethod
    def _confidence_in_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        return v


# --- Repeating sub-structures (lists on the proforma) -----------------------
# These are NOT wrapped in Field[T]: a list is provenance-tracked at the
# container level via the None-vs-[] convention, and individual line items are
# captured wholesale rather than field-by-field.


class SIP(BaseModel):
    fund_name: str | None = None
    monthly_amount: float
    category: Literal["equity", "debt", "hybrid", "elss", "unsure"] = "unsure"


class FD(BaseModel):
    amount: float
    tenure_months: int | None = None
    rate_pct: float | None = None


class OtherInvestment(BaseModel):
    """PPF / NPS / stocks / gold — typed so metrics are derivable (LLD §4, §9.3)."""

    label: str
    kind: Literal["ppf", "nps", "stocks", "gold", "other"] = "other"
    annual_amount: float | None = None  # recurring annual contribution (feeds 80C for ppf)
    current_value: float | None = None  # corpus value (feeds asset-allocation)


class Goal(BaseModel):
    label: str
    target_amount: float | None = None
    horizon_years: float | None = None
    priority: Literal["low", "med", "high"] = "med"


class Proforma(BaseModel):
    """The finalized financial profile. All scalar values are provenance-wrapped."""

    # Identity
    name: Field[str]
    age: Field[int]
    city: Field[str] | None = None
    dependents: Field[int]
    tax_regime: Field[Literal["old", "new", "unsure"]]
    # Income
    monthly_take_home: Field[float]
    annual_ctc: Field[float] | None = None
    other_income_monthly: Field[float] | None = None
    # Investments
    epf_monthly: Field[float]  # EMPLOYEE contribution (the 80C-eligible part); see §9.3
    sips: list[SIP] = []
    fds: list[FD] = []
    other_investments: list[OtherInvestment] = []
    existing_corpus: Field[float] | None = None
    # Expenses
    fixed_household_monthly: Field[float]
    emi_total_monthly: Field[float] | None = None
    travel_annual: Field[float] | None = None
    adhoc_monthly: Field[float] | None = None
    # Protection
    health_insurance_cover: Field[float]  # 0 if none
    term_life_cover: Field[float]  # 0 if none
    emergency_fund: Field[float]
    # Goals / Risk
    goals: list[Goal] = []
    risk_appetite: Field[Literal["low", "med", "high", "unsure"]]


def _make_partial(model: type[BaseModel], name: str) -> type[BaseModel]:
    """Mirror `model` with every top-level field optional + defaulting to None.

    Derived (not hand-maintained) so `PartialProforma` and `Proforma` can never
    drift. List fields become `None` by default here — which is exactly the
    "not yet asked" sentinel the coverage logic relies on (§5.4): `None` =
    unprobed, `[]` = asked and the user has none.
    """
    overrides = {
        field_name: (Optional[info.annotation], None)
        for field_name, info in model.model_fields.items()
    }
    return create_model(name, __base__=BaseModel, **overrides)


# All-optional working draft mirror (LLD §4, §5.1).
PartialProforma = _make_partial(Proforma, "PartialProforma")


class ExtractedFacts(BaseModel):
    """The **flat** extraction DTO the LLM emits (LLD §4, §5.3) — NOT the stored shape.

    Why flat: asking a model to populate the nested `Field{value,source,confidence}`
    wrapper 20+ times is unreliable (smaller/free models just null it). So the LLM
    emits **plain values** plus one `confidence` map; `extract_node` re-applies the
    `Field[T]` provenance in code (source is always `ai_extracted` — the model never
    decides provenance). List fields follow the None-vs-`[]` convention.
    """

    # Identity
    name: str | None = None
    age: int | None = None
    city: str | None = None
    dependents: int | None = None
    tax_regime: Literal["old", "new", "unsure"] | None = None
    # Income
    monthly_take_home: float | None = None
    annual_ctc: float | None = None
    other_income_monthly: float | None = None
    # Investments
    epf_monthly: float | None = None  # EMPLOYEE contribution (80C-eligible part)
    sips: list[SIP] | None = None
    fds: list[FD] | None = None
    other_investments: list[OtherInvestment] | None = None
    existing_corpus: float | None = None
    # Expenses
    fixed_household_monthly: float | None = None
    emi_total_monthly: float | None = None
    travel_annual: float | None = None
    adhoc_monthly: float | None = None
    # Protection
    health_insurance_cover: float | None = None
    term_life_cover: float | None = None
    emergency_fund: float | None = None
    # Goals / Risk
    goals: list[Goal] | None = None
    risk_appetite: Literal["low", "med", "high", "unsure"] | None = None
    # Per-field confidence the model assigns to each value it emitted (0..1).
    confidence: dict[str, float] = {}


# Field names that are provenance-wrapped scalars vs. wholesale-replaced lists.
LIST_FIELDS = ("sips", "fds", "other_investments", "goals")
SCALAR_FIELDS = tuple(
    name for name in ExtractedFacts.model_fields if name not in (*LIST_FIELDS, "confidence")
)
