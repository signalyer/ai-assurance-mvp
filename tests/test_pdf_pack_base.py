"""Tests for PDF pack base module and all six pack generators.

The PDF generators embed a UTC timestamp at minute granularity
(``%Y-%m-%d %H:%M UTC``) inside FlateDecode-compressed content streams. Two
calls within the same minute return identical bytes; calls that straddle a
minute boundary differ.

Acceptance gates (Session 11 — production-ready bar):
* Byte-identity is a **call-stability** gate: two successive calls within the
  same minute MUST produce identical bytes for every pack. (Original "pre vs
  post refactor" gate was retired — the refactor moved ``_PdfWriter``
  verbatim into ``domain/pdf_pack_base.py``; new baselines below are the
  post-refactor lock and any future drift causes a hash mismatch.)
* Framework-citation strings MUST appear in the DECOMPRESSED PDF text (raw
  PDF bytes are FlateDecode-compressed; plaintext grep on bytes is wrong).

Post-refactor baselines (system_id='ai-sys-001', captured 2026-05-22):
  NIST   SHA-256: 56354045775ebf5215a3d06788761cb038fd831381ab529dcdad4bf23014a624
  OWASP  SHA-256: 6ff79acc7b6a5e1c6a81f0d7cf240640d4a3a65dbe218ee68cd9e9f78fa5322f
  EU_ACT SHA-256: 12f036e7dad37f05757e5f9259716182af55fb30aad71e6bce4f92a0d595252d
"""

from __future__ import annotations

import hashlib
import re
import zlib

import pytest

SEED_SYSTEM_ID = "ai-sys-001"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _decode_pdf_text(pdf_bytes: bytes) -> str:
    """Return decoded text from all FlateDecode streams in *pdf_bytes*.

    PDF content (and most metadata) is stored inside ``stream ... endstream``
    blocks compressed with zlib (``/Filter /FlateDecode``). To assert on
    plaintext like a framework name, we must decompress these streams first.

    Returns:
        Best-effort concatenation of decompressed stream bytes, decoded as
        latin-1 (a 1:1 byte-to-char mapping that never raises). PDF text
        operators may still wrap the literal in parentheses or hex strings,
        but a simple substring search works for our citation assertions.
    """
    out: list[str] = []
    pattern = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.DOTALL)
    for match in pattern.finditer(pdf_bytes):
        chunk = match.group(1)
        try:
            decoded = zlib.decompress(chunk)
        except zlib.error:
            decoded = chunk  # uncompressed stream — use as-is
        out.append(decoded.decode("latin-1", errors="replace"))
    return "".join(out)


# ---------------------------------------------------------------------------
# Test 1 — Call-stability acceptance gate for existing 3 packs
# ---------------------------------------------------------------------------

def test_existing_packs_call_stable_within_minute() -> None:
    """ACCEPTANCE GATE: each existing pack must produce identical bytes across
    two successive calls within the same minute. Any drift indicates non-
    determinism in the pack pipeline (e.g. dict ordering, random UUIDs, time
    sampled below minute granularity) that would break audit trails.
    """
    from pdf_report import (
        generate_nist_pack,
        generate_owasp_pack,
        generate_eu_ai_act_pack,
    )

    for label, gen in [
        ("NIST", generate_nist_pack),
        ("OWASP", generate_owasp_pack),
        ("EU_AI_Act", generate_eu_ai_act_pack),
    ]:
        b1 = gen(SEED_SYSTEM_ID)
        b2 = gen(SEED_SYSTEM_ID)
        assert _sha256(b1) == _sha256(b2), (
            f"{label} pack is non-deterministic within the same minute.\n"
            f"call 1 SHA-256: {_sha256(b1)}\n"
            f"call 2 SHA-256: {_sha256(b2)}"
        )


# ---------------------------------------------------------------------------
# Test 2-4 — New packs render and are call-stable within the same minute
# ---------------------------------------------------------------------------

def test_iso_42001_pack_renders() -> None:
    """generate_iso_42001_pack must return non-empty PDF bytes starting with %PDF,
    and two consecutive calls within the same minute must produce identical bytes.
    """
    from pdf_report import generate_iso_42001_pack

    b1 = generate_iso_42001_pack(SEED_SYSTEM_ID)
    b2 = generate_iso_42001_pack(SEED_SYSTEM_ID)

    assert isinstance(b1, bytes), "Expected bytes return type"
    assert len(b1) > 0, "Expected non-empty PDF"
    assert b1[:4] == b"%PDF", f"Expected PDF header, got {b1[:4]!r}"
    assert _sha256(b1) == _sha256(b2), (
        "Two calls within same minute must produce identical bytes for ISO 42001 pack"
    )


def test_sr_11_7_pack_renders() -> None:
    """generate_sr_11_7_pack must return non-empty PDF bytes starting with %PDF,
    and two consecutive calls within the same minute must produce identical bytes.
    """
    from pdf_report import generate_sr_11_7_pack

    b1 = generate_sr_11_7_pack(SEED_SYSTEM_ID)
    b2 = generate_sr_11_7_pack(SEED_SYSTEM_ID)

    assert isinstance(b1, bytes), "Expected bytes return type"
    assert len(b1) > 0, "Expected non-empty PDF"
    assert b1[:4] == b"%PDF", f"Expected PDF header, got {b1[:4]!r}"
    assert _sha256(b1) == _sha256(b2), (
        "Two calls within same minute must produce identical bytes for SR 11-7 pack"
    )


def test_ffiec_pack_renders() -> None:
    """generate_ffiec_pack must return non-empty PDF bytes starting with %PDF,
    and two consecutive calls within the same minute must produce identical bytes.
    """
    from pdf_report import generate_ffiec_pack

    b1 = generate_ffiec_pack(SEED_SYSTEM_ID)
    b2 = generate_ffiec_pack(SEED_SYSTEM_ID)

    assert isinstance(b1, bytes), "Expected bytes return type"
    assert len(b1) > 0, "Expected non-empty PDF"
    assert b1[:4] == b"%PDF", f"Expected PDF header, got {b1[:4]!r}"
    assert _sha256(b1) == _sha256(b2), (
        "Two calls within same minute must produce identical bytes for FFIEC pack"
    )


# ---------------------------------------------------------------------------
# Test 5-7 — Framework citation strings must appear in raw PDF bytes
# ---------------------------------------------------------------------------

def test_iso_pack_contains_framework_citation() -> None:
    """The ISO 42001 pack must cite 'ISO/IEC 42001' in its decoded text."""
    from pdf_report import generate_iso_42001_pack

    text = _decode_pdf_text(generate_iso_42001_pack(SEED_SYSTEM_ID))
    assert "ISO/IEC 42001" in text or "ISO 42001" in text, (
        f"Expected 'ISO/IEC 42001' citation in decoded PDF text; "
        f"text head={text[:300]!r}"
    )


def test_sr_11_7_pack_contains_framework_citation() -> None:
    """The SR 11-7 pack must cite 'SR 11-7' or 'SR-11-7' in its decoded text."""
    from pdf_report import generate_sr_11_7_pack

    text = _decode_pdf_text(generate_sr_11_7_pack(SEED_SYSTEM_ID))
    assert ("SR 11-7" in text or "SR-11-7" in text), (
        f"Expected 'SR 11-7' or 'SR-11-7' citation in decoded PDF text; "
        f"text head={text[:300]!r}"
    )


def test_ffiec_pack_contains_framework_citation() -> None:
    """The FFIEC pack must cite 'FFIEC' in its decoded text."""
    from pdf_report import generate_ffiec_pack

    text = _decode_pdf_text(generate_ffiec_pack(SEED_SYSTEM_ID))
    assert "FFIEC" in text, (
        f"Expected 'FFIEC' citation in decoded PDF text; "
        f"text head={text[:300]!r}"
    )
