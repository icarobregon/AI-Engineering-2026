"""Composition tests for the estimation/v2 prompt templates (conservative calibration)."""

from app.prompts.loader import render_estimation_prompt
from app.schemas.estimation import (
    DetailLevel,
    EstimationRequest,
    OutputFormat,
    ProjectType,
)


def _request(**overrides) -> EstimationRequest:
    base = dict(
        description="A mobile chat application with login, push notifications and Stripe checkout.",
        project_type=ProjectType.MOBILE_APP,
        detail_level=DetailLevel.DETAILED,
        output_format=OutputFormat.PHASES_TABLE,
    )
    base.update(overrides)
    return EstimationRequest(**base)


def test_v2_system_contains_conservative_calibration_keywords():
    system, _ = render_estimation_prompt(_request(), version="v2")
    lowered = system.lower()
    assert "safety margin" in lowered
    assert "calibration" in lowered
    assert "risks" in lowered


def test_v2_system_requires_risks_section_in_output():
    system, _ = render_estimation_prompt(_request(), version="v2")
    assert "### Risks" in system


def test_v2_system_differs_from_v1():
    system_v1, _ = render_estimation_prompt(_request(), version="v1")
    system_v2, _ = render_estimation_prompt(_request(), version="v2")
    assert system_v1 != system_v2
    # v2 is materially longer (extra calibration + risks sections).
    assert len(system_v2) > len(system_v1)


def test_v2_user_prompt_matches_v1_shape():
    _, user_v1 = render_estimation_prompt(_request(), version="v1")
    _, user_v2 = render_estimation_prompt(_request(), version="v2")
    assert user_v1 == user_v2
