"""Onboarding artifacts for vendor_risk — intake payloads + lifespan bootstrap.

The two canonical intake payloads (intake_payload_ext.json,
intake_payload_int.json) are the source of truth for the AISystem rows
backing this agent. The bootstrap module reads them on engine startup and
invokes api.intake.submit_intake() with a deterministic system_id_override
so the rows land with predictable IDs across cold starts.
"""
from __future__ import annotations
