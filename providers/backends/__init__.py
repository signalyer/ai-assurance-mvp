"""Backends sub-package — concrete implementations of provider protocols.

Available backend modules:
  scrubber_presidio   — Presidio NER + regex + Fernet vault
  scrubber_regex      — regex-only fallback (no Presidio dependency)
  tracer_langfuse     — Langfuse Cloud tracer + stdout-only alternative
  deepeval_evaluator  — DeepEval 5-metric suite
  memory_postgres     — Postgres episodic memory (SQLAlchemy)
  rag_azure_search    — Azure AI Search hybrid retrieval
  noop                — safe no-op implementations for all five protocols
"""
