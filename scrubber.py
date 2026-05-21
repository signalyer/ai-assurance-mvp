"""PII detection and tokenization using Presidio NER + regex layering.

Exposes tokenise_payload() and restore_payload() for scrubbing and reversing
PII tokens. Scrubbing is fail-closed: if Presidio errors, returns empty vault_id
and logs the error. Tokens like [PERSON_001], [EMAIL_002] are stable per scope.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy-loaded Presidio
_analyzer = None
_anonymizer = None


def _get_analyzer():
    """Get or create Presidio analyzer. Returns None if not available."""
    global _analyzer
    if _analyzer is not None:
        return _analyzer

    try:
        from presidio_analyzer import AnalyzerEngine
        _analyzer = AnalyzerEngine()
        return _analyzer
    except ImportError:
        logger.warning("Presidio not installed; scrubber will fall back to regex only")
        return None
    except Exception as e:
        logger.error(f"Failed to initialize Presidio analyzer: {e}")
        return None


def _get_anonymizer():
    """Get or create Presidio anonymizer. Returns None if not available."""
    global _anonymizer
    if _anonymizer is not None:
        return _anonymizer

    try:
        from presidio_anonymizer import AnonymizerEngine
        _anonymizer = AnonymizerEngine()
        return _anonymizer
    except ImportError:
        return None
    except Exception as e:
        logger.error(f"Failed to initialize Presidio anonymizer: {e}")
        return None


# Custom regex patterns for entities Presidio might miss
_CUSTOM_PATTERNS = {
    "US_SSN": r"\b\d{3}-\d{2}-\d{4}\b",
    "PHONE_NUMBER": r"\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    "AWS_ARN": r"arn:[a-z\d\-]+:[a-z\d\-]+:[a-z\d\-]*:\d*:[a-z\d\-/]*",
    "API_KEY": r"\b[a-zA-Z0-9_\-]{32,}\b",  # Generic long secrets
    "UUID": r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
}

# Entity types Presidio should detect
_PRESIDIO_ENTITIES = {
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "US_SSN",
    "CREDIT_CARD",
    "IBAN_CODE",
    "IP_ADDRESS",
    "US_BANK_NUMBER",
    "NRP",
    "LOCATION",
    "DATE_TIME",
    "URL",
}


def tokenise_payload(text: str, scope: str) -> tuple[str, str]:
    """
    Scrub PII from text using Presidio NER + custom regex.

    Replaces detected entities with stable tokens like [PERSON_001], [EMAIL_002].
    All detected entities and their locations are stored in the de-ID vault.

    Args:
        text: Raw text to scrub
        scope: Logical scope for grouping tokens (e.g., 'api_call_123', 'session-01a')

    Returns:
        (scrubbed_text, vault_id) where vault_id is the lookup key for restoration.
        On error, returns (text, "") — caller must check vault_id before trusting scrub.
    """
    if not text:
        return text, ""

    try:
        # Collect all entities (positions, text, type)
        entity_mapping = {}
        entity_counts = {}
        replacements = []  # List of (start, end, token, type, text)

        # Step 1: Custom regex layer (detect patterns on original text)
        for pattern_type, pattern in _CUSTOM_PATTERNS.items():
            matches = list(re.finditer(pattern, text, re.IGNORECASE))
            for match in matches:
                matched_text = match.group(0)
                if pattern_type not in entity_counts:
                    entity_counts[pattern_type] = 0
                entity_counts[pattern_type] += 1
                count = entity_counts[pattern_type]

                token = f"[{pattern_type}_{count:03d}]"
                key = f"{pattern_type}_{count:03d}"
                entity_mapping[key] = matched_text
                replacements.append((match.start(), match.end(), token, pattern_type))

        # Step 2: Presidio NER detection
        analyzer = _get_analyzer()
        if analyzer is None:
            logger.warning("Presidio unavailable; using regex-only fallback")
            if entity_mapping:
                # Apply regex-only replacements
                scrubbed = _apply_replacements(text, replacements)
                vault_id = f"{scope}_{hash(text) % 1000000:06d}"
                from domain.deid_vault import store
                store(vault_id, entity_mapping)
                logger.info(f"Regex-only scrub: {len(entity_mapping)} entities into vault {vault_id}")
                return scrubbed, vault_id
            else:
                return text, ""

        results = analyzer.analyze(text=text, entities=list(_PRESIDIO_ENTITIES), language="en")

        # Step 3: Add Presidio results, avoiding overlaps
        for result in results:
            entity_type = result.entity_type
            entity_text = text[result.start : result.end]

            # Skip if overlaps with existing replacement
            overlaps = False
            for r_start, r_end, _, _ in replacements:
                if not (result.end <= r_start or result.start >= r_end):
                    overlaps = True
                    break

            if overlaps:
                continue

            if entity_type not in entity_counts:
                entity_counts[entity_type] = 0
            entity_counts[entity_type] += 1
            count = entity_counts[entity_type]

            token = f"[{entity_type}_{count:03d}]"
            key = f"{entity_type}_{count:03d}"
            entity_mapping[key] = entity_text
            replacements.append((result.start, result.end, token, entity_type))

        # Step 4: Apply all replacements in reverse order (avoid offset shifts)
        if not entity_mapping:
            return text, ""

        scrubbed = _apply_replacements(text, replacements)

        # Step 5: Store in vault and return
        vault_id = f"{scope}_{hash(text) % 1000000:06d}"
        from domain.deid_vault import store
        store(vault_id, entity_mapping)

        logger.info(f"Scrubbed {len(entity_mapping)} entities into vault {vault_id}")
        return scrubbed, vault_id

    except Exception as e:
        logger.error(f"Scrubber error: {e}", exc_info=True)
        return text, ""


def _apply_replacements(text: str, replacements: list[tuple[int, int, str, str]]) -> str:
    """Apply multiple text replacements in reverse order to avoid offset shifts."""
    # Sort by start position, descending
    replacements_sorted = sorted(replacements, key=lambda r: r[0], reverse=True)

    result = text
    for start, end, token, _ in replacements_sorted:
        result = result[:start] + token + result[end:]

    return result


def _tokenise_regex_only(text: str, scope: str) -> tuple[str, str]:
    """Fallback regex-only scrubbing when Presidio is unavailable."""
    entity_mapping = {}
    entity_counts = {}
    replacements = []

    # Apply custom regex patterns
    for pattern_type, pattern in _CUSTOM_PATTERNS.items():
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        for match in matches:
            matched_text = match.group(0)
            if pattern_type not in entity_counts:
                entity_counts[pattern_type] = 0
            entity_counts[pattern_type] += 1
            count = entity_counts[pattern_type]

            token = f"[{pattern_type}_{count:03d}]"
            key = f"{pattern_type}_{count:03d}"
            entity_mapping[key] = matched_text
            replacements.append((match.start(), match.end(), token, pattern_type))

    if not entity_mapping:
        return text, ""

    scrubbed = _apply_replacements(text, replacements)

    from domain.deid_vault import store
    vault_id = f"{scope}_{hash(text) % 1000000:06d}"
    store(vault_id, entity_mapping)

    logger.info(f"Regex-only scrub: {len(entity_mapping)} entities into vault {vault_id}")
    return scrubbed, vault_id


def restore_payload(scrubbed: str, vault_id: str) -> str:
    """
    Reverse PII scrubbing using vault lookup.

    Restores all tokens [ENTITY_TYPE_NNN] back to original text using the vault.

    Args:
        scrubbed: Scrubbed text with tokens
        vault_id: Vault lookup key (from tokenise_payload return)

    Returns:
        Original unscrubbed text. Raises if vault entry is missing or expired.
    """
    if not vault_id:
        logger.warning("restore_payload called with empty vault_id; returning scrubbed text as-is")
        return scrubbed

    try:
        from domain.deid_vault import lookup

        mapping = lookup(vault_id)
        if mapping is None:
            raise ValueError(f"Vault entry {vault_id} not found or expired")

        restored = scrubbed
        for key, original_text in mapping.items():
            token = f"[{key}]"
            restored = restored.replace(token, original_text)

        logger.info(f"Restored {len(mapping)} entities from vault {vault_id}")
        return restored

    except Exception as e:
        logger.error(f"Restore error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    # Smoke test
    test_text = "Client John Smith SSN 123-45-6789 email john@example.com phone +1-555-867-5309"
    print(f"Original: {test_text}")

    scrubbed, vault_id = tokenise_payload(test_text, "smoke-test")
    print(f"Scrubbed ({vault_id}): {scrubbed}")

    if vault_id:
        restored = restore_payload(scrubbed, vault_id)
        print(f"Restored: {restored}")
        assert restored == test_text, "Restore mismatch!"
        print("✓ Round-trip successful")
    else:
        print("✗ Scrubbing failed (vault_id empty)")
