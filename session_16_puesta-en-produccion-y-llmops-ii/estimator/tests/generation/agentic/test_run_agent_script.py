"""The demo CLI's two pieces of real logic (Session 12).

``main()`` needs a live client and is left to manual runs, but the stub loader and
the report renderer are logic that breaks silently: the loader depends on the kit
file's location AND on its function signature, and the renderer is what the
deliverable trace is read from.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.generation.agentic.agent_schemas import AgentEstimate, EstimatedComponent

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "run_agent_s12.py"


def _script_module():
    spec = importlib.util.spec_from_file_location("run_agent_s12", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_stub_backend_loads_the_kit_file_and_matches_the_backend_signature():
    # The kit stub is standalone (no app imports) and is loaded by path, so a
    # moved file or a renamed function only shows up at runtime — unless this
    # test catches it. It must also accept the keywords the tool passes.
    search = _script_module()._load_stub_backend()

    items = await search("OAuth2 authentication backend with JWT", sectors=None, year_min=None)

    assert items and all("estimated_hours" in item for item in items)


async def test_stub_backend_honours_the_sector_filter():
    search = _script_module()._load_stub_backend()

    assert await search("mobile app for couriers", sectors=["nonexistent-sector"]) == []


def test_report_renders_grounded_and_ungrounded_components_differently():
    estimate = AgentEstimate(
        project="RUTA",
        components=[
            EstimatedComponent(
                name="Backend", estimated_hours=96.6, rationale="2 analogues", grounded=True
            ),
            EstimatedComponent(
                name="ERP", estimated_hours=0.0, rationale="none found", grounded=False
            ),
        ],
        total_hours=96.6,
        notes="one gap",
    )

    report = _script_module()._render_estimate(estimate)

    # A number with no evidence behind it must not read like one that has it.
    assert "Backend: 96.6h" in report
    assert "[NOT GROUNDED]" in report
    assert report.count("[NOT GROUNDED]") == 1
    assert "TOTAL: 96.6h" in report
