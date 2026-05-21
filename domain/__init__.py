"""Domain layer for the Enterprise AI Assurance Platform.

Strongly typed Pydantic models for AI systems, assessments, frameworks, controls,
findings, release gates, evidence, runtime events, policies, approvals, and
exceptions/waivers — anchored to the financial-services use case.

Importing the package exposes:
  - All entity models and enums from `domain.models`
  - Realistic FS seed data from `domain.seed`
"""

from domain.models import *  # noqa: F401,F403
from domain import seed  # noqa: F401
from domain import controls  # noqa: F401
from domain.controls import (  # noqa: F401
    CONTROLS, CONTROLS_BY_ID,
    is_applicable,
    get_controls_for_ai_system, get_required_controls,
    map_control_to_frameworks, calculate_control_coverage,
    ControlCoverageRow, ControlCoverageReport,
)
