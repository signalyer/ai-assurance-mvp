"""YAML framework loader for the AI Assurance Platform.

Loads YAML framework definition files, validates them with Pydantic v2,
and returns lists of domain FrameworkItem instances that can be merged
directly with the existing Python-native catalogs.

Public API:
    load_yaml_framework(path: str) -> list[FrameworkItem]
    load_all_frameworks() -> dict[str, list[FrameworkItem]]
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from domain.framework_coverage import FrameworkItem


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_FRAMEWORK_SLUGS: frozenset[str] = frozenset({
    "eu-ai-act",
    "iso-42001",
    "sr-11-7",
    "ffiec",
    "us-finserv-overlay",
})

SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({"1.0"})

# Map YAML framework slug -> FrameworkName enum value used in FrameworkItem
_SLUG_TO_FRAMEWORK_VALUE: dict[str, str] = {
    "eu-ai-act": "EU_AI_ACT",
    "iso-42001": "ISO_42001",
    "sr-11-7": "SR_11_7",
    "ffiec": "FFIEC",
    "us-finserv-overlay": "US_FINSERV_OVERLAY",
}

_FRAMEWORKS_DIR: Path = Path(__file__).parent.resolve()


# ---------------------------------------------------------------------------
# Pydantic v2 schema for YAML file validation
# ---------------------------------------------------------------------------

class FrameworkYAMLItem(BaseModel):
    """Schema for a single item entry in a framework YAML file."""

    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    description: str
    exact_clauses: list[str] = []
    prefix_clauses: list[str] = []
    recommended_owner: Optional[str] = None


class FrameworkYAMLFile(BaseModel):
    """Schema for the top-level structure of a framework YAML file."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    framework: str
    display_name: str
    recommended_owner: str
    items: list[FrameworkYAMLItem]


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def load_yaml_framework(path: str) -> list[FrameworkItem]:
    """Load a single framework YAML file and return validated FrameworkItem instances.

    Performs fail-closed validation: unknown framework slug, unsupported schema
    version, malformed YAML, and missing required fields all raise immediately.

    The resolved file path must be inside the frameworks directory; any attempt
    to load a file outside that directory raises ValueError (path confinement).

    Args:
        path: Absolute or relative path to the YAML framework file.

    Returns:
        List of FrameworkItem instances ready to merge with existing catalogs.

    Raises:
        ValueError: Path outside frameworks directory, unknown framework slug,
            or unsupported schema version.
        yaml.YAMLError: Malformed YAML content (re-raised with file path context).
        pydantic.ValidationError: Missing or invalid required fields.
        FileNotFoundError: Path does not exist.
    """
    # --- Finding #1: path confinement — resolve BEFORE opening the file ---
    file_path = Path(path).resolve()
    if not file_path.is_relative_to(_FRAMEWORKS_DIR):
        raise ValueError(f"Path outside frameworks directory: {path}")

    if not file_path.exists():
        raise FileNotFoundError(f"Framework YAML file not found: {path}")

    raw_text = file_path.read_text(encoding="utf-8")

    try:
        raw_data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise yaml.YAMLError(f"Malformed YAML in {path}: {exc}") from exc

    if raw_data is None or not isinstance(raw_data, dict):
        raise yaml.YAMLError(f"Empty or non-mapping YAML content in {path}")

    # Validate schema version before full Pydantic parse
    schema_ver = raw_data.get("schema_version")
    if schema_ver not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(
            f"Unsupported schema version: {schema_ver!r}. "
            f"Supported: {', '.join(sorted(SUPPORTED_SCHEMA_VERSIONS))}"
        )

    # Validate framework slug before full Pydantic parse
    framework_slug = raw_data.get("framework")
    if framework_slug not in ALLOWED_FRAMEWORK_SLUGS:
        raise ValueError(
            f"Unknown framework slug: {framework_slug!r}. "
            f"Allowed: {', '.join(sorted(ALLOWED_FRAMEWORK_SLUGS))}"
        )

    try:
        validated = FrameworkYAMLFile.model_validate(raw_data)
    except ValidationError:
        # Finding #15: bare re-raise preserves the original ValidationError
        raise

    framework_value = _SLUG_TO_FRAMEWORK_VALUE[validated.framework]

    items: list[FrameworkItem] = []
    for yaml_item in validated.items:
        owner = yaml_item.recommended_owner or validated.recommended_owner
        items.append(
            FrameworkItem(
                id=yaml_item.id,
                framework=framework_value,
                display_name=yaml_item.display_name,
                description=yaml_item.description,
                exact_clauses=yaml_item.exact_clauses,
                prefix_clauses=yaml_item.prefix_clauses,
                recommended_owner=owner,
            )
        )

    return items


def load_all_frameworks() -> dict[str, list[FrameworkItem]]:
    """Load all YAML framework files from the frameworks/ directory.

    Discovers every ``*.yaml`` file in the same directory as this module,
    loads and validates each one, and returns a mapping keyed by the
    framework slug defined inside each file.

    Returns:
        Dict mapping framework slug (e.g. ``"eu-ai-act"``) to its list of
        validated FrameworkItem instances.

    Raises:
        ValueError: Any file contains an unknown slug or unsupported schema version.
        yaml.YAMLError: Any file contains malformed YAML.
        pydantic.ValidationError: Any file is missing required fields.
    """
    result: dict[str, list[FrameworkItem]] = {}

    yaml_files = sorted(_FRAMEWORKS_DIR.glob("*.yaml"))

    for yaml_file in yaml_files:
        items = load_yaml_framework(str(yaml_file))
        if items:
            # Determine slug from the framework field of the first item's framework value
            # by reversing the mapping
            framework_value = items[0].framework
            slug = next(
                (s for s, v in _SLUG_TO_FRAMEWORK_VALUE.items() if v == framework_value),
                framework_value,
            )
            result[slug] = items

    return result
