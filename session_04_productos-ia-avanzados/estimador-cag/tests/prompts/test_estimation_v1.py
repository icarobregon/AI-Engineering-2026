"""Composition tests for the estimation/v1 prompt templates.

These tests render the templates with various EstimationRequest configurations
and assert structural properties of the resulting strings. They do NOT call any
LLM and must run in milliseconds.
"""

import pytest
import structlog

from app.prompts.loader import render_estimation_prompt
from app.schemas.estimation import (
    DetailLevel,
    EstimationRequest,
    OutputFormat,
    ProjectType,
)


def _request(**overrides) -> EstimationRequest:
    base = dict(
        description="Mobile app with login, chat and push notifications across iOS and Android.",
        project_type=ProjectType.MOBILE_APP,
        detail_level=DetailLevel.DETAILED,
        output_format=OutputFormat.PHASES_TABLE,
    )
    base.update(overrides)
    return EstimationRequest(**base)


def test_user_prompt_wraps_description_in_project_description_tag():
    system, user = render_estimation_prompt(_request())
    assert "<project_description>" in user
    assert "Mobile app with login" in user
    assert "</project_description>" in user


@pytest.mark.parametrize(
    "fmt,expected_in_system,absent_in_system",
    [
        (OutputFormat.PHASES_TABLE, "phases_table", "narrative"),
        (OutputFormat.NARRATIVE, "narrative", "phases_table"),
        (OutputFormat.LINE_ITEMS, "line_items", "phases_table"),
    ],
)
def test_output_format_switches_system_block(fmt, expected_in_system, absent_in_system):
    system, _ = render_estimation_prompt(_request(output_format=fmt))
    # The chosen format's keyword appears in the rendered system prompt.
    assert expected_in_system in system
    # The exact "Structure the response as a <other>" line for a different
    # format must NOT be present.
    assert f"Structure the response as a {absent_in_system}" not in system


def test_detailed_level_requests_assumptions_summary_does_not():
    system_detailed, _ = render_estimation_prompt(_request(detail_level=DetailLevel.DETAILED))
    system_summary, _ = render_estimation_prompt(_request(detail_level=DetailLevel.SUMMARY))
    assert "assumptions" in system_detailed.lower()
    assert "list the assumptions" not in system_summary.lower()


def test_loader_accepts_version_parameter():
    system, user = render_estimation_prompt(_request(), version="v1")
    assert system and user


def test_loader_raises_on_unknown_version():
    from jinja2 import TemplateNotFound

    with pytest.raises(TemplateNotFound):
        render_estimation_prompt(_request(), version="v999")


def test_loader_emits_prompt_rendered_log_with_hash_and_version():
    with structlog.testing.capture_logs() as logs:
        render_estimation_prompt(_request(), version="v1")

    rendered_events = [log for log in logs if log.get("event") == "prompt_rendered"]
    assert len(rendered_events) == 1
    event = rendered_events[0]
    assert event["version"] == "v1"
    assert "prompt_hash" in event
    assert len(event["prompt_hash"]) == 12
    assert event["num_references"] >= 0
