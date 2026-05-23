"""Shared PDF building blocks for compliance pack generators.

Extracted from pdf_report.py in Session 11.  All pack generators
(NIST, OWASP, EU AI Act, ISO 42001, SR 11-7, FFIEC) import from here.

Nothing in this module is changed from the original pdf_report.py
implementation — the move is verbatim to preserve byte-identity.
"""

from __future__ import annotations

import hashlib
import io
import zlib
from typing import Any


class _PdfWriter:
    """Minimal PDF 1.4 writer using only stdlib.

    Creates a single-stream document with one page per section.
    Text is rendered using the built-in Helvetica font family.

    Finding #7: the dead first-pass _alloc_obj / _offsets / _pages fields have
    been removed.  The second pass (out2) is self-sufficient and produces valid
    PDF output as confirmed by b'%PDF' header presence in tests.

    Finding #8: pages_id is computed from the object count layout declared
    explicitly at the top of build(); an assertion verifies correctness before
    the xref is written.
    """

    # PDF spec: points per inch
    _A4_W = 595
    _A4_H = 842
    _MARGIN = 50
    _LINE_H = 14
    _FONT_BODY = 10
    _FONT_HEAD = 13
    _FONT_TITLE = 18
    _FONT_SMALL = 8

    def __init__(self) -> None:
        self._buf = io.BytesIO()
        self._page_streams: list[bytes] = []

        # We collect all content into pages; each page is a separate content stream.
        self._cur_page_lines: list[str] = []   # PDF graphic operators for current page
        self._cur_y: float = self._A4_H - self._MARGIN
        self._page_num: int = 0
        self._header_text: str = ""

    # ------------------------------------------------------------------
    # Public page API
    # ------------------------------------------------------------------

    def set_header(self, header: str) -> None:
        """Set a repeated footer text (system_id + framework)."""
        self._header_text = header

    def new_page(self) -> None:
        """Flush the current page and start a fresh one."""
        if self._cur_page_lines or self._page_num == 0:
            self._flush_page()
        self._page_num += 1
        self._cur_y = self._A4_H - self._MARGIN
        self._cur_page_lines = []
        self._add_footer()

    def _add_footer(self) -> None:
        """Draw footer with page number and header text."""
        y = 20.0
        self._cur_page_lines.append(
            f"BT /F2 {self._FONT_SMALL} Tf {self._MARGIN} {y} Td "
            f"({self._pdf_str(self._header_text)}) Tj ET"
        )
        self._cur_page_lines.append(
            f"BT /F2 {self._FONT_SMALL} Tf "
            f"{self._A4_W - self._MARGIN - 30} {y} Td "
            f"(Page {self._page_num}) Tj ET"
        )

    def title(self, text: str) -> None:
        """Render a large title line."""
        self._ensure_space(self._FONT_TITLE + 8)
        self._cur_page_lines.append(
            f"BT /F1 {self._FONT_TITLE} Tf {self._MARGIN} {self._cur_y} Td "
            f"({self._pdf_str(text)}) Tj ET"
        )
        self._cur_y -= self._FONT_TITLE + 8

    def heading(self, text: str) -> None:
        """Render a section heading."""
        self._ensure_space(self._FONT_HEAD + 6)
        self._cur_page_lines.append(
            f"BT /F1 {self._FONT_HEAD} Tf {self._MARGIN} {self._cur_y} Td "
            f"({self._pdf_str(text)}) Tj ET"
        )
        self._cur_y -= self._FONT_HEAD + 6

    def body(self, text: str, indent: float = 0) -> None:
        """Render a body text line, wrapping if necessary."""
        max_chars = int((self._A4_W - 2 * self._MARGIN - indent) / 6)
        for chunk in self._wrap(text, max_chars):
            self._ensure_space(self._LINE_H)
            x = self._MARGIN + indent
            self._cur_page_lines.append(
                f"BT /F2 {self._FONT_BODY} Tf {x} {self._cur_y} Td "
                f"({self._pdf_str(chunk)}) Tj ET"
            )
            self._cur_y -= self._LINE_H

    def spacer(self, pts: float = 8) -> None:
        """Advance the cursor downward by `pts` points."""
        self._cur_y -= pts

    def rule(self) -> None:
        """Draw a thin horizontal rule."""
        self._ensure_space(6)
        y = self._cur_y
        self._cur_page_lines.append(
            f"{self._MARGIN} {y} m {self._A4_W - self._MARGIN} {y} l S"
        )
        self._cur_y -= 6

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> bytes:
        """Flush the last page and assemble the final PDF bytes.

        Finding #7: the dead first-pass (_alloc_obj stub) has been removed
        entirely.  All object IDs are pre-allocated explicitly at the start of
        this method.

        Finding #8: pages_id is computed from the known object layout and
        asserted to match the actual written pages-dict object ID before
        writing the xref table.

        Object layout (1-based):
          1              : resources (fonts)
          2 .. 2N        : content stream + page dict pairs (N pages)
          2 + 2N         : pages dict
          3 + 2N         : catalog
        """
        if self._cur_page_lines:
            self._flush_page()

        n_pages = len(self._page_streams)

        # Pre-allocate object IDs deterministically
        resources_id = 1
        # content_id for page i (0-indexed): 2 + i*2
        # page_dict_id for page i (0-indexed): 3 + i*2
        pages_id_expected = 2 + n_pages * 2        # first obj after all page pairs
        catalog_id = pages_id_expected + 1
        total_objects = catalog_id                  # highest 1-based id used

        out = io.BytesIO()
        out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: list[int] = []

        def _write_obj(idx_1based: int, data: bytes) -> None:
            offsets.append(out.tell())
            out.write(f"{idx_1based} 0 obj\n".encode())
            out.write(data)
            out.write(b"\nendobj\n")

        # Object 1: resources (fonts)
        _write_obj(resources_id, (
            b"<< /Font << "
            b"/F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >> "
            b"/F2 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> "
            b">> >>"
        ))

        content_ids: list[int] = []
        page_ids: list[int] = []
        obj_id = resources_id + 1

        for stream in self._page_streams:
            compressed = zlib.compress(stream)
            content_obj_id = obj_id
            _write_obj(content_obj_id, (
                f"<< /Filter /FlateDecode /Length {len(compressed)} >>".encode()
                + b"\nstream\n" + compressed + b"\nendstream"
            ))
            content_ids.append(content_obj_id); obj_id += 1

            page_obj_id = obj_id
            _write_obj(page_obj_id, (
                f"<< /Type /Page /Parent {pages_id_expected} 0 R "
                f"/MediaBox [0 0 {self._A4_W} {self._A4_H}] "
                f"/Resources {resources_id} 0 R "
                f"/Contents {content_obj_id} 0 R >>".encode()
            ))
            page_ids.append(page_obj_id); obj_id += 1

        # pages dict — assert ID matches pre-allocated expectation
        assert obj_id == pages_id_expected, (
            f"pages_id mismatch: expected {pages_id_expected}, got {obj_id}. "
            "Object layout has changed — update pre-allocation."
        )
        kids_str = " ".join(f"{i} 0 R" for i in page_ids)
        _write_obj(obj_id, (
            f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids_str}] >>".encode()
        ))
        pages_id_actual = obj_id; obj_id += 1

        # catalog
        assert obj_id == catalog_id, (
            f"catalog_id mismatch: expected {catalog_id}, got {obj_id}."
        )
        _write_obj(obj_id, (
            f"<< /Type /Catalog /Pages {pages_id_actual} 0 R >>".encode()
        ))
        obj_id += 1

        # xref
        xref_offset = out.tell()
        out.write(f"xref\n0 {obj_id}\n".encode())
        out.write(b"0000000000 65535 f \n")
        for off in offsets:
            out.write(f"{off:010d} 00000 n \n".encode())

        out.write(
            f"trailer\n<< /Size {obj_id} /Root {catalog_id} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n".encode()
        )
        return out.getvalue()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _flush_page(self) -> None:
        """Serialise the current page lines to the page stream buffer."""
        stream_text = "\n".join(self._cur_page_lines)
        self._page_streams.append(stream_text.encode("latin-1", errors="replace"))

    def _ensure_space(self, need: float) -> None:
        """Overflow to a new page if there is not enough vertical space."""
        if self._cur_y - need < 60:
            self._flush_page()
            self._page_num += 1
            self._cur_page_lines = []
            self._cur_y = self._A4_H - self._MARGIN
            self._add_footer()

    @staticmethod
    def _pdf_str(text: str) -> str:
        """Escape a string for use inside PDF literal parentheses."""
        return (
            text.replace("\\", "\\\\")
                .replace("(", "\\(")
                .replace(")", "\\)")
                .replace("\n", " ")
                .replace("\r", " ")
        )

    @staticmethod
    def _wrap(text: str, width: int) -> list[str]:
        """Word-wrap text to at most `width` characters per line."""
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            if len(current) + len(word) + 1 <= width:
                current = word if not current else current + " " + word
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [""]


# ---------------------------------------------------------------------------
# Evidence helpers shared by all pack generators
# ---------------------------------------------------------------------------

def _compute_evidence_hash(ev_id: str, summary: str, collected_at: str) -> str:
    """Return SHA-256 hex digest computed from evidence content fields."""
    raw = f"{ev_id}|{summary}|{collected_at}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_system_and_evidence(system_id: str) -> tuple[Any, list[Any]]:
    """Return (AISystem, list[Evidence]) for the given system_id.

    The concrete types are ``domain.models.AISystem`` and
    ``domain.models.Evidence``; they are typed as ``Any`` here to avoid a
    circular import (``domain.pdf_pack_base`` is itself imported by
    ``pdf_report`` and ``domain.repository``).
    """
    from domain import repository
    system = repository.get_ai_system(system_id)
    if system is None:
        raise ValueError(f"AI system '{system_id}' not found.")
    evidence = repository.evidence_for(system_id)
    return system, evidence


def _render_evidence_appendix(pdf: _PdfWriter, evidence: list, system_id: str) -> None:
    """Write the evidence appendix section to pdf."""
    if not evidence:
        return
    pdf.new_page()
    pdf.heading("Evidence Appendix — SHA-256 Hashes")
    pdf.rule()
    pdf.spacer()
    for ev in evidence:
        collected_str = (
            ev.collected_at.isoformat()
            if hasattr(ev.collected_at, "isoformat")
            else str(ev.collected_at)
        )
        ev_hash = _compute_evidence_hash(ev.id, ev.summary, collected_str)
        pdf.body(f"ID: {ev.id}", indent=0)
        pdf.body(f"Type: {ev.evidence_type.value}  |  Source: {ev.source}", indent=10)
        pdf.body(f"Collected: {collected_str}", indent=10)
        pdf.body(f"Summary: {ev.summary}", indent=10)
        pdf.body(f"SHA-256: {ev_hash}", indent=10)
        pdf.spacer(4)


def _render_item_section(
    pdf: _PdfWriter,
    framework_display: str,
    items_coverage: list,
    evidence: list,
    system_id: str,
) -> None:
    """Write one section per framework item with control mapping + findings."""
    control_id_to_evidence: dict[str, list] = {}
    for ev in evidence:
        for cid in (ev.linked_control_ids or []):
            control_id_to_evidence.setdefault(cid, []).append(ev)

    for ic in items_coverage:
        pdf.heading(f"{ic.display_name}  ({ic.coverage_pct:.0f}% covered)")
        pdf.body(ic.description)
        pdf.spacer(4)

        if ic.mapped_controls:
            pdf.body("Controls:", indent=0)
            for c in ic.mapped_controls:
                pdf.body(
                    f"  [{c.status}] {c.control_id} — {c.title} "
                    f"(priority: {c.priority}, findings: {c.open_findings})",
                    indent=10,
                )
                # Link evidence
                for ev in control_id_to_evidence.get(c.control_id, [])[:3]:
                    collected_str = (
                        ev.collected_at.isoformat()
                        if hasattr(ev.collected_at, "isoformat")
                        else str(ev.collected_at)
                    )
                    ev_hash = _compute_evidence_hash(ev.id, ev.summary, collected_str)
                    pdf.body(
                        f"    Evidence: {ev.id} | SHA-256: {ev_hash[:16]}...",
                        indent=20,
                    )

        if ic.related_findings:
            pdf.body("Open Findings:", indent=0)
            for f in ic.related_findings[:5]:
                pdf.body(
                    f"  [{f.severity}] {f.id} — {f.title}",
                    indent=10,
                )

        if ic.recommended_remediation:
            pdf.body("Remediation:", indent=0)
            for rem in ic.recommended_remediation[:3]:
                pdf.body(f"  {rem}", indent=10)

        pdf.rule()
        pdf.spacer(4)
