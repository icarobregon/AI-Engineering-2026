"""Unit tests for the agent's tools (Session 12).

The two arithmetic tools are pure functions and are tested directly; the search
tool is tested against a fake backend, which is the seam the real pipeline and the
kit stub both plug into. No network, no database.
"""

from __future__ import annotations

import json

from app.generation.agentic.agent_tools import (
    CONTINGENCY_FACTOR,
    TOOLS,
    calculate_estimate,
    dispatch_tool,
    validate_estimate,
)


def _payload(result) -> dict:
    return json.loads(result.output)


# --- tool schemas -----------------------------------------------------------


def test_schemas_are_flat_and_strict():
    # The Responses API shape: type/name/description at the same level, NOT nested
    # under a "function" key like Chat Completions.
    for tool in TOOLS:
        assert tool["type"] == "function"
        assert "function" not in tool
        assert tool["name"] and tool["description"]
        assert tool["strict"] is True
        params = tool["parameters"]
        assert params["additionalProperties"] is False
        # strict mode: every declared property must also be required.
        assert set(params["required"]) == set(params["properties"])


# --- calculate_estimate -----------------------------------------------------


def test_calculate_estimate_uses_median_plus_contingency():
    result = calculate_estimate(
        {"components": [{"name": "Auth backend", "reference_amounts": [380.0, 420.0, 400.0]}]}
    )
    payload = _payload(result)
    assert payload["components"][0]["estimated_hours"] == round(400.0 * (1 + CONTINGENCY_FACTOR), 1)
    assert payload["total_hours"] == payload["components"][0]["estimated_hours"]


def test_calculate_estimate_median_resists_an_outlier():
    # The mean of these is 1000; the median is 400. A single oversized analogue
    # must not drag the estimate with it.
    result = calculate_estimate(
        {"components": [{"name": "Backend", "reference_amounts": [380.0, 400.0, 420.0, 2800.0]}]}
    )
    assert _payload(result)["components"][0]["estimated_hours"] < 600


def test_calculate_estimate_flags_components_without_references():
    result = calculate_estimate(
        {
            "components": [
                {"name": "Mobile app", "reference_amounts": [700.0]},
                {"name": "ERP integration", "reference_amounts": []},
            ]
        }
    )
    payload = _payload(result)
    unbudgeted = [c for c in payload["components"] if c["unbudgeted"]]
    assert [c["name"] for c in unbudgeted] == ["ERP integration"]
    # Never invented: costed at zero and named in the observation.
    assert unbudgeted[0]["estimated_hours"] == 0.0
    assert "ERP integration" in result.observation


# --- validate_estimate ------------------------------------------------------


def _validate_args(components: list[dict]) -> dict:
    """Run calculate_estimate and hand its OUTPUT to validate_estimate.

    This is the contract between the two tools: the validator checks the numbers
    that were produced, it does not re-derive them. Building the arguments this
    way is what keeps the pair honest — a validator with its own copy of the cost
    formula would agree with itself even if the formula were wrong.
    """
    priced = _payload(calculate_estimate({"components": components}))
    by_name = {c["name"]: c["estimated_hours"] for c in priced["components"]}
    return {
        "components": [
            {
                "name": c["name"],
                "estimated_hours": by_name[c["name"]],
                "reference_amounts": c["reference_amounts"],
            }
            for c in components
        ],
        "total_hours": priced["total_hours"],
    }


def test_validate_estimate_accepts_what_calculate_estimate_produced():
    args = _validate_args([{"name": "Backend", "reference_amounts": [400.0]}])
    assert _payload(validate_estimate(args))["ok"] is True


def test_validate_estimate_reports_total_mismatch_and_missing_references():
    args = _validate_args(
        [
            {"name": "Backend", "reference_amounts": [400.0]},
            {"name": "Dashboard", "reference_amounts": []},
        ]
    )
    args["total_hours"] = 9999.0  # the model misreports the total it was given
    payload = _payload(validate_estimate(args))
    assert payload["ok"] is False
    assert any("unbudgeted" in issue for issue in payload["issues"])
    assert any("total mismatch" in issue for issue in payload["issues"])


def test_validate_estimate_checks_the_hours_it_was_given_not_a_recomputation():
    # Hours that do NOT follow from the references: the validator must judge the
    # 4000h it was handed, not quietly recompute 460h from [400] and pass.
    payload = _payload(
        validate_estimate(
            {
                "components": [
                    {
                        "name": "Backend",
                        "estimated_hours": 40000.0,
                        "reference_amounts": [400.0],
                    }
                ],
                "total_hours": 40000.0,
            }
        )
    )
    assert payload["ok"] is False
    assert any("plausible band" in issue for issue in payload["issues"])


def test_validate_estimate_flags_a_component_priced_below_the_band():
    payload = _payload(
        validate_estimate(
            {
                "components": [
                    {"name": "Tiny", "estimated_hours": 2.0, "reference_amounts": [1.7]}
                ],
                "total_hours": 2.0,
            }
        )
    )
    assert any("plausible band" in issue for issue in payload["issues"])


async def test_dispatch_routes_every_declared_tool():
    # Each tool in TOOLS must be reachable through dispatch_tool: a name that is
    # advertised to the model but not routed is answered as "unknown tool".
    args = {
        "search_budgets": {"query": "auth backend", "filters": None},
        "calculate_estimate": {"components": [{"name": "A", "reference_amounts": [100.0]}]},
        "validate_estimate": {
            "components": [{"name": "A", "estimated_hours": 115.0, "reference_amounts": [100.0]}],
            "total_hours": 115.0,
        },
    }
    for tool in TOOLS:
        result = await dispatch_tool(tool["name"], args[tool["name"]], backend=_backend)
        assert result.error is False, tool["name"]


# --- search_budgets + dispatch ---------------------------------------------


async def _backend(query, *, sectors=None, year_min=None, year_max=None, **_kw):
    assert sectors is None or isinstance(sectors, list)
    return [
        {
            "id": 1,
            "content_preview": "OAuth2 backend",
            "sector": "finance",
            "budget_id": "BUD-1",
            "estimated_hours": 420.0,
            "distance": 0.21,
        }
    ]


async def test_search_budgets_returns_items_and_a_readable_observation():
    result = await dispatch_tool(
        "search_budgets", {"query": "OAuth2 auth backend", "filters": None}, backend=_backend
    )
    assert _payload(result)["count"] == 1
    assert "420" in result.observation


async def test_search_budgets_passes_filters_through():
    seen = {}

    async def backend(query, *, sectors=None, year_min=None, year_max=None, **_kw):
        seen.update(query=query, sectors=sectors, year_min=year_min)
        return []

    await dispatch_tool(
        "search_budgets",
        {
            "query": "mobile app",
            "filters": {"sectors": ["logistics"], "year_min": 2022, "year_max": None},
        },
        backend=backend,
    )
    assert seen == {"query": "mobile app", "sectors": ["logistics"], "year_min": 2022}


async def test_empty_search_is_reported_not_faked():
    async def empty_backend(query, **_kw):
        return []

    result = await dispatch_tool(
        "search_budgets", {"query": "quantum blockchain", "filters": None}, backend=empty_backend
    )
    assert _payload(result)["count"] == 0
    assert result.error is False  # an empty result is an answer, not a failure


async def test_dispatch_returns_tool_failures_to_the_model_instead_of_raising():
    async def broken_backend(query, **_kw):
        raise RuntimeError("pgvector is down")

    result = await dispatch_tool(
        "search_budgets", {"query": "backend", "filters": None}, backend=broken_backend
    )
    assert result.error is True
    assert "pgvector is down" in _payload(result)["error"]


async def test_dispatch_rejects_an_unknown_tool():
    result = await dispatch_tool("delete_everything", {}, backend=_backend)
    assert result.error is True


async def test_empty_search_tells_the_model_what_to_do_next():
    """The anti-thrash hint must reach the MODEL (output), not just the trace.

    A live gpt-5 run rephrased the same component four times because an empty
    result carried no instruction; the guidance was going to the observation,
    which the model never sees.
    """

    async def empty_backend(query, **_kw):
        return []

    result = await dispatch_tool(
        "search_budgets", {"query": "SAP IDoc middleware", "filters": None}, backend=empty_backend
    )
    hint = _payload(result)["hint"]
    assert "empty reference_amounts" in hint
    assert "unbudgeted" in hint
