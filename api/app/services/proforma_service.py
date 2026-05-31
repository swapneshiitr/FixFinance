"""Proforma service (LLD §9) — versioning + derived metrics.

Three jobs:
  - `finalize`     — snapshot the interview draft as proforma version 1.
  - `apply_edit`   — validate a PATCH, write a NEW version (append-only, FR2.5).
  - `compute_derived` — rule-based metrics (NO LLM): cheaper, testable, predictable.

The derived-metrics math is deliberately deterministic Python. The LLM is never
asked to compute a ratio.
"""
from __future__ import annotations

import uuid

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Proforma as ProformaRow
from app.schemas.proforma import LIST_FIELDS, SCALAR_FIELDS, PartialProforma

_80C_CAP = 150_000  # Section 80C annual deduction ceiling (₹)


class ProformaNotFound(Exception):
    """No proforma with that id is owned by the user."""


class InvalidEdit(Exception):
    """A PATCH referenced an unknown field or produced an invalid proforma."""


# --- value accessors over the Field-wrapped JSONB shape ---------------------


def _val(data: dict, key: str):
    f = data.get(key)
    return f.get("value") if isinstance(f, dict) else None


def _items(data: dict, key: str) -> list:
    v = data.get(key)
    return v if isinstance(v, list) else []


# --- derived metrics (LLD §9.3) ---------------------------------------------


def compute_derived(data: dict) -> dict:
    """Compute the rule-based metrics from a proforma `data` dict. Guards /0 → None."""
    flags: list[str] = []

    def ratio(num, den) -> float | None:
        if num is None:
            return None
        if not den:  # None or 0 → undefined
            return None
        return round(num / den, 4)

    take_home = _val(data, "monthly_take_home")
    fixed = _val(data, "fixed_household_monthly") or 0
    emi = _val(data, "emi_total_monthly") or 0
    adhoc = _val(data, "adhoc_monthly") or 0
    travel_annual = _val(data, "travel_annual") or 0
    total_monthly_expenses = fixed + emi + adhoc + travel_annual / 12

    epf_monthly = _val(data, "epf_monthly") or 0
    sips = _items(data, "sips")
    fds = _items(data, "fds")
    other = _items(data, "other_investments")

    sip_monthly = sum((s.get("monthly_amount") or 0) for s in sips)
    oi_monthly = sum((o.get("annual_amount") or 0) / 12 for o in other)
    monthly_investment_outflow = epf_monthly + sip_monthly + oi_monthly

    if not take_home:
        flags.append("monthly_take_home missing/zero → income ratios unavailable")
    if not total_monthly_expenses:
        flags.append("total_monthly_expenses zero → expense ratios unavailable")

    # Asset allocation (LLD §9.3): current_value where known, else annualized flow.
    equity = debt = 0.0
    for s in sips:
        amt = (s.get("monthly_amount") or 0) * 12
        cat = s.get("category")
        if cat in ("equity", "elss"):
            equity += amt
        elif cat in ("debt", "hybrid"):
            debt += amt
    for o in other:
        base = o.get("current_value")
        if base is None:
            base = o.get("annual_amount") or 0
        kind = o.get("kind")
        if kind == "stocks":
            equity += base
        elif kind in ("ppf", "nps"):
            debt += base
        # gold / other → not classified into equity|debt|cash for the MVP
    debt += epf_monthly * 12
    debt += sum((f.get("amount") or 0) for f in fds)
    cash = _val(data, "emergency_fund") or 0
    total_alloc = equity + debt + cash
    if total_alloc > 0:
        asset_allocation_mix = {
            "equity": round(equity / total_alloc, 4),
            "debt": round(debt / total_alloc, 4),
            "cash": round(cash / total_alloc, 4),
        }
    else:
        asset_allocation_mix = None
        flags.append("asset_allocation: no classifiable positions")

    # 80C utilization — epf_monthly is the EMPLOYEE share (LLD §4, §9.3).
    epf_employee_annual = epf_monthly * 12
    elss_annual = 12 * sum((s.get("monthly_amount") or 0) for s in sips if s.get("category") == "elss")
    ppf_annual = sum((o.get("annual_amount") or 0) for o in other if o.get("kind") == "ppf")
    tax_saving_80c_utilization = round(
        min(1.0, (epf_employee_annual + elss_annual + ppf_annual) / _80C_CAP), 4
    )

    return {
        "total_monthly_expenses": round(total_monthly_expenses, 2),
        "monthly_investment_outflow": round(monthly_investment_outflow, 2),
        "savings_rate": ratio(monthly_investment_outflow, take_home),
        "expense_to_income_ratio": ratio(total_monthly_expenses, take_home),
        "emergency_fund_months": ratio(_val(data, "emergency_fund"), total_monthly_expenses),
        "asset_allocation_mix": asset_allocation_mix,
        "tax_saving_80c_utilization": tax_saving_80c_utilization,
        "flags": flags,
    }


# --- persistence ------------------------------------------------------------


async def finalize(session: AsyncSession, user_id: uuid.UUID, draft: dict) -> ProformaRow:
    """Snapshot the interview draft as proforma version 1 (source=ai_extracted)."""
    row = ProformaRow(
        id=uuid.uuid4(),
        version=1,
        user_id=user_id,
        source="ai_extracted",
        data=draft,
        derived=compute_derived(draft),
    )
    session.add(row)
    await session.commit()
    return row


async def get_latest(
    session: AsyncSession, proforma_id: uuid.UUID, user_id: uuid.UUID
) -> ProformaRow | None:
    """Latest version of a logical proforma, scoped to its owner."""
    return (
        await session.execute(
            select(ProformaRow)
            .where(ProformaRow.id == proforma_id, ProformaRow.user_id == user_id)
            .order_by(ProformaRow.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def get_version(
    session: AsyncSession, proforma_id: uuid.UUID, version: int
) -> ProformaRow | None:
    """Fetch a specific (id, version) — used by the report job, which pins a version."""
    return (
        await session.execute(
            select(ProformaRow).where(
                ProformaRow.id == proforma_id, ProformaRow.version == version
            )
        )
    ).scalar_one_or_none()


async def apply_edit(
    session: AsyncSession, proforma_id: uuid.UUID, user_id: uuid.UUID, edits: dict
) -> ProformaRow:
    """Apply a PATCH as a NEW version (append-only). Scalars become user_edited.

    `edits` maps top-level field names → new values: a scalar value for a
    Field-wrapped field, or a full list for a list field. Raises `InvalidEdit`
    for unknown fields or a result that fails Proforma validation.
    """
    latest = await get_latest(session, proforma_id, user_id)
    if latest is None:
        raise ProformaNotFound(str(proforma_id))

    merged = dict(latest.data)
    for field, value in edits.items():
        if field in SCALAR_FIELDS:
            merged[field] = {"value": value, "source": "user_edited", "confidence": 1.0}
        elif field in LIST_FIELDS:
            merged[field] = value  # full-list replacement
        else:
            raise InvalidEdit(f"unknown field: {field}")

    try:
        PartialProforma.model_validate(merged)  # type-check the edited draft
    except ValidationError as e:
        raise InvalidEdit(str(e)) from e

    row = ProformaRow(
        id=proforma_id,
        version=latest.version + 1,
        user_id=user_id,
        source="user_edited",
        data=merged,
        derived=compute_derived(merged),
    )
    session.add(row)
    await session.commit()
    return row
