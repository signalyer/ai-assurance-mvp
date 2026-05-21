"""Presidio-backed scrubber — calls scrubber._tokenise_impl / _restore_impl.

CIRCULAR IMPORT PREVENTION:
  After Session 05 proxy refactoring, scrubber.tokenise_payload() is a proxy:
    tokenise_payload(text, scope) -> get_scrubber().tokenise(text, scope)
                                   -> PresidioScrubber.tokenise(text, scope)

  Calling scrubber.tokenise_payload() from this method creates INFINITE RECURSION:
    tokenise_payload -> get_scrubber().tokenise -> PresidioScrubber.tokenise
    -> tokenise_payload -> get_scrubber().tokenise -> ... (stack overflow)

  The fix: call scrubber._tokenise_impl() and scrubber._restore_impl() (private
  functions that contain the actual Presidio + regex logic WITHOUT the proxy layer).

Fail-closed behaviour is inherited from _tokenise_impl:
  - If Presidio is unavailable, falls back to regex-only (see scrubber.py).
  - On any error, _tokenise_impl returns (text, "") — vault_id is empty.
  - Callers must check vault_id before trusting the scrub result.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class PresidioScrubber:
    """ScrubberBackend that delegates to scrubber._tokenise_impl / _restore_impl."""

    def tokenise(self, text: str, scope: str) -> tuple[str, str]:
        """Scrub PII from *text* using Presidio NER + regex layer.

        Calls scrubber._tokenise_impl() (private) NOT scrubber.tokenise_payload()
        (public proxy) to break the circular call chain described in the module docstring.

        Args:
            text:  Raw input text that may contain PII.
            scope: Logical grouping label for the vault entry.

        Returns:
            (scrubbed_text, vault_id) — vault_id is empty string when no PII found
            or when scrubbing fails (fail-closed: callers must check vault_id).
        """
        logger.debug(
            "PresidioScrubber.tokenise: entry scope=%s text_length=%d",
            scope, len(text),
        )
        from scrubber import _tokenise_impl  # private impl — not the public proxy

        scrubbed, vault_id = _tokenise_impl(text, scope)
        logger.debug(
            "PresidioScrubber.tokenise: exit vault_id=%s scrubbed_length=%d",
            vault_id or "(empty)", len(scrubbed),
        )
        return scrubbed, vault_id

    def restore(self, scrubbed: str, vault_id: str) -> str:
        """Reverse PII tokenisation using the de-ID vault.

        Calls scrubber._restore_impl() (private) NOT scrubber.restore_payload()
        (public proxy) to avoid recursive call chain.

        Args:
            scrubbed: Scrubbed text containing [ENTITY_TYPE_NNN] tokens.
            vault_id: Key returned by a prior tokenise() call.

        Returns:
            Original text with all tokens replaced by their PII values.

        Raises:
            ValueError: If vault_id is missing or expired.
        """
        logger.debug(
            "PresidioScrubber.restore: entry vault_id=%s scrubbed_length=%d",
            vault_id or "(empty)", len(scrubbed),
        )
        from scrubber import _restore_impl  # private impl — not the public proxy

        restored = _restore_impl(scrubbed, vault_id)
        logger.debug(
            "PresidioScrubber.restore: exit restored_length=%d",
            len(restored),
        )
        return restored
