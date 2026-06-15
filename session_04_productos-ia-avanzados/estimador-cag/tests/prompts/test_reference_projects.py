"""Tests for the server-side reference projects loader and its template wiring."""

import pytest

from app.prompts import references as references_module
from app.prompts.loader import render_estimation_prompt
from app.prompts.references import load_reference_projects
from app.schemas.estimation import (
    DetailLevel,
    EstimationRequest,
    OutputFormat,
    ProjectType,
    ReferenceProject,
)


@pytest.mark.parametrize("project_type", list(ProjectType))
def test_loader_filters_by_project_type(project_type):
    refs = load_reference_projects(project_type)
    assert all(isinstance(r, ReferenceProject) for r in refs)
    assert all(r.project_type == project_type for r in refs)


def test_seed_covers_all_project_types():
    for pt in ProjectType:
        assert load_reference_projects(pt), f"no reference projects for {pt}"


def _request(**overrides) -> EstimationRequest:
    base = dict(
        description="A typical project description used in tests, long enough to pass validation.",
        project_type=ProjectType.MOBILE_APP,
        detail_level=DetailLevel.DETAILED,
        output_format=OutputFormat.PHASES_TABLE,
    )
    base.update(overrides)
    return EstimationRequest(**base)


def test_system_renders_reference_projects_block_when_refs_present():
    system, _ = render_estimation_prompt(_request())
    assert "<reference_projects>" in system
    assert "Outcome:" in system


def test_system_omits_reference_projects_block_when_no_refs(monkeypatch):
    monkeypatch.setattr(references_module, "load_reference_projects", lambda _pt: [])
    # The loader imports load_reference_projects by name at module load time;
    # patch it in the loader's namespace too.
    from app.prompts import loader as loader_module

    monkeypatch.setattr(loader_module, "load_reference_projects", lambda _pt: [])

    system, _ = render_estimation_prompt(_request())
    assert "<reference_projects>" not in system
