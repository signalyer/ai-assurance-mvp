"""Regex-only scrubber backend — no Presidio dependency.

This backend implements the ScrubberBackend Protocol using only the custom
regex patterns defined in scrubber.py (_CUSTOM_PATTERNS).
It is the intended fallback when Presidio is not installed (e.g. a slim runtime
image or a CI environment without heavy NLP dependencies).

Fail-closed behaviour mirrors scrubber.py:
  - On any error, tokenise() returns (text, "") — vault_id is empty.
  - Callers must check vault_id before trusting the scrub result.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Mirror the custom patterns from scrubber.py — kept in sync manually.
# If scrubber._CUSTOM_PATTERNS changes, update this list too.
_CUSTOM_PATTERNS: dict[str, str] = {
    "US_SSN": r"\b\d{3}-\d{2}-\d{4}\b",
    "PHONE_NUMBER": r"\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    "AWS_ARN": r"arn:[a-z\d\-]+:[a-z\d\-]+:[a-z\d\-]*:\d*:[a-z\d\-/]*",
    # Known-prefix secrets only — generic 32+ char strings are NOT matched to
    # avoid false-positives on UUIDs, hashes, and base64 document IDs.
    # Covered prefixes:
    #   sk-           OpenAI / Anthropic API keys
    #   AKIA          AWS access key IDs  (exactly 16 uppercase alphanumeric after prefix)
    #   ghp_          GitHub personal access tokens
    #   xox[baprs]-   Slack tokens (bot, app, personal, refresh, service)
    "API_KEY": r"(?:sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|xox[baprs]-[A-Za-z0-9\-]{10,})",
    "UUID": r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
}


def _apply_replacements(
    text: str,
    replacements: list[tuple[int, int, str, str]],
) -> str:
    """Apply a list of (start, end, token, type) replacements in reverse position order.

    Reverse order prevents earlier replacements from shifting offsets of later ones.

    Args:
        text:         Input text to modify.
        replacements: List of (start_idx, end_idx, replacement_token, entity_type).

    Returns:
        Text with all replacements applied.
    """
    sorted_reps = sorted(replacements, key=lambda r: r[0], reverse=True)
    result = text
    for start, end, token, _ in sorted_reps:
        result = result[:start] + token + result[end:]
    return result


class RegexScrubber:
    """ScrubberBackend using regex-only pattern matching (no Presidio).

    Covers: US SSN, phone numbers, AWS ARNs, generic API keys (32+ chars), UUIDs.
    Email, person names, and other NER-detected entities are NOT covered —
    use PresidioScrubber for full coverage.
    """

    def tokenise(self, text: str, scope: str) -> tuple[str, str]:
        """Detect and replace PII in *text* using regex patterns only.

        Stores detected entities in the de-ID vault (same vault used by
        PresidioScrubber) so restore() works identically.

        Args:
            text:  Raw input text.
            scope: Logical grouping label for the vault entry.

        Returns:
            (scrubbed_text, vault_id) — vault_id is empty string when no PII
            found or on error (fail-closed).
        """
        if not text:
            return text, ""

        logger.debug(
            "RegexScrubber.tokenise: entry scope=%s text_length=%d",
            scope, len(text),
        )

        try:
            entity_mapping: dict[str, str] = {}
            entity_counts: dict[str, int] = {}
            replacements: list[tuple[int, int, str, str]] = []

            for pattern_type, pattern in _CUSTOM_PATTERNS.items():
                matches = list(re.finditer(pattern, text, re.IGNORECASE))
                for match in matches:
                    matched_text = match.group(0)
                    entity_counts[pattern_type] = entity_counts.get(pattern_type, 0) + 1
                    count = entity_counts[pattern_type]
                    token = f"[{pattern_type}_{count:03d}]"
                    key = f"{pattern_type}_{count:03d}"
                    entity_mapping[key] = matched_text
                    replacements.append((match.start(), match.end(), token, pattern_type))

            if not entity_mapping:
                logger.debug("RegexScrubber.tokenise: no PII found — returning original text")
                return text, ""

            scrubbed = _apply_replacements(text, replacements)
            vault_id = f"{scope}_{hash(text) % 1000000:06d}"

            from domain.deid_vault import store  # deferred to avoid circular import at module load

            store(vault_id, entity_mapping)
            logger.info(
                "RegexScrubber.tokenise: %d entities scrubbed vault_id=%s",
                len(entity_mapping), vault_id,
            )
            return scrubbed, vault_id

        except Exception as exc:
            logger.error("RegexScrubber.tokenise: error — %s", exc, exc_info=True)
            return text, ""

    def restore(self, scrubbed: str, vault_id: str) -> str:
        """Reverse regex scrubbing using vault lookup.

        Delegates to domain.deid_vault.lookup() — the same vault used by the
        Presidio backend, so cross-backend restore is not supported (each
        vault_id is only valid for the backend that created it).

        Args:
            scrubbed: Text containing [ENTITY_TYPE_NNN] placeholder tokens.
            vault_id: Key from a prior tokenise() call.

        Returns:
            Original text with all tokens replaced.

        Raises:
            ValueError: If vault_id is missing or expired.
        """
        if not vault_id:
            logger.warning("RegexScrubber.restore: empty vault_id — returning scrubbed as-is")
            return scrubbed

        logger.debug(
            "RegexScrubber.restore: entry vault_id=%s scrubbed_length=%d",
            vault_id, len(scrubbed),
        )

        try:
            from domain.deid_vault import lookup  # deferred to avoid circular import

            mapping = lookup(vault_id)
            if mapping is None:
                raise ValueError(f"Vault entry {vault_id!r} not found or expired")

            restored = scrubbed
            for key, original_text in mapping.items():
                token = f"[{key}]"
                restored = restored.replace(token, original_text)

            logger.info(
                "RegexScrubber.restore: %d tokens restored vault_id=%s",
                len(mapping), vault_id,
            )
            return restored

        except Exception as exc:
            logger.error("RegexScrubber.restore: error — %s", exc, exc_info=True)
            raise
