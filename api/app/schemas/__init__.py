"""Pydantic schemas — the validation + serialization contracts (LLD §4, §11.4).

`proforma` holds THE core contract: the single source of truth that validates
user edits, persists as JSONB, and is handed to Claude as the extraction schema.
"""
