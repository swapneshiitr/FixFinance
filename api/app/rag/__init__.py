"""RAG subsystem (LLD §10, SG3).

Config-driven, source-cited financial principles → embedded into pgvector →
retrieved per report finding so recommendations cite an authentic source. The
knowledge lives as editable YAML (`api/knowledge/principles/*.yaml`), never as
hardcoded prose, so policy/interpretation can change without code changes.
"""
