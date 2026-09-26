"""The agent's tools: JSON Schemas, implementations and dispatch.

Two things worth knowing before editing this file.

**The schemas are FLAT.** The Responses API expects
``{"type": "function", "name": ..., "description": ..., "parameters": ...}``, not
the Chat Completions shape that nests everything under a ``function`` key. With
``strict: true`` every property must appear in ``required`` and every object must
set ``additionalProperties: false``; optional arguments are expressed as nullable
types, not as absent keys.

**The descriptions are the contract.** They are the only thing the model reads to
decide which tool to call and with what — it never sees this code. When the agent
picks the wrong tool or invents arguments, the description is the first suspect.
The one in ``search_budgets`` spends its words on the rule that matters most for
this exercise: one call per component, never a merged query.

``search_budgets`` reaches the retrieval pipeline through an INJECTED backend
rather than importing it: ``generation/agentic`` may not import a ``generation``
sibling (ARCHITECTURE.md §3). ``dependencies.get_budget_search_backend()`` wires
the real one; the kit stub plugs into the same seam for offline debugging.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import structlog

from app.generation.agentic.agent_schemas import (
    CalculateEstimateArgs,
    SearchBudgetsArgs,
    ValidateEstimateArgs,
)

log = structlog.get_logger()

# A flat buffer on every component's central estimate. Transparent on purpose:
# one number, applied once, visible in the breakdown — no hidden multipliers.
CONTINGENCY_FACTOR = 0.15

# Sanity band for a single component, in engineer-hours. Anything outside it is
# reported by validate_estimate as suspicious — not corrected silently.
_MIN_PLAUSIBLE_HOURS = 8.0
_MAX_PLAUSIBLE_HOURS = 4000.0

# One search returns at most this many historical items to the model. Keeping it
# small keeps the observation readable and the context cheap.
_MAX_ITEMS_IN_OBSERVATION = 5

BudgetSearchBackend = Callable[..., Awaitable[list[dict[str, Any]]]]


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "search_budgets",
        "description": (
            "Search historical project budgets for work comparable to ONE component "
            "of the project being estimated. Each result is a SUBSYSTEM of a past "
            "project — one module, priced at the hours all of its tasks actually "
            "took — so the numbers are directly comparable to a component of the "
            "project you are estimating. Call it once per component, with a query "
            "describing that component alone: a backend, an ERP integration, a "
            "mobile app and an analytics dashboard are different kinds of work with "
            "different costs, so a query that merges them retrieves an average that "
            "describes none of them. Write the query IN ENGLISH — the historical budget "
            "corpus is written in English, and a query in another language "
            "retrieves measurably worse or nothing at all. Describe the work "
            "(technologies, scope, constraints); do not phrase it as a question. "
            "If a search "
            "comes back empty or with items that are clearly about something else, "
            "rephrase and search again before giving up on that component."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "English description of ONE component's work, e.g. 'SAP ERP "
                        "integration syncing invoicing and customer master data via "
                        "IDocs with retry handling'."
                    ),
                },
                "filters": {
                    "type": ["object", "null"],
                    "description": (
                        "Optional narrowing. Use it only when the transcript "
                        "justifies it — an unnecessary filter can exclude the very "
                        "budgets you are looking for."
                    ),
                    "properties": {
                        "sectors": {
                            "type": ["array", "null"],
                            "items": {"type": "string"},
                            "description": (
                                "Restrict to these client sectors. Known values: "
                                "finance, ecommerce, healthcare, industrial, "
                                "logistics, education, media, government."
                            ),
                        },
                        "year_min": {
                            "type": ["integer", "null"],
                            "description": "Oldest project year to consider.",
                        },
                        "year_max": {
                            "type": ["integer", "null"],
                            "description": "Newest project year to consider.",
                        },
                    },
                    "required": ["sectors", "year_min", "year_max"],
                    "additionalProperties": False,
                },
            },
            "required": ["query", "filters"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "calculate_estimate",
        "description": (
            "Turn the historical hours you gathered into a costed breakdown. Pass "
            "EVERY component of the project in a single call, each with the "
            "engineer-hours of the comparable budgets you found for it "
            "(reference_amounts). The arithmetic is deterministic and done here, "
            "not by you: a median per component plus a fixed contingency buffer, "
            "then the total. Pass an empty reference_amounts for a component you "
            "found nothing for — it will be flagged as unbudgeted rather than "
            "guessed, which tells you to search again."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "components": {
                    "type": "array",
                    "description": "Every component to cost, in one call.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Component name as stated in the transcript.",
                            },
                            "reference_amounts": {
                                "type": "array",
                                "items": {"type": "number"},
                                "description": (
                                    "Engineer-hours of the historical items "
                                    "search_budgets returned for THIS component. "
                                    "Leave it empty only when the searches returned "
                                    "nothing at all — not because the analogues come "
                                    "from a different sector."
                                ),
                            },
                        },
                        "required": ["name", "reference_amounts"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["components"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "validate_estimate",
        "description": (
            "Check a finished estimate before you report it. Pass back the "
            "breakdown calculate_estimate gave you, unchanged. Reports components "
            "with no historical backing, component hours outside a plausible band, "
            "and a total that does not match the sum of its parts. Call it as the "
            "LAST step, after calculate_estimate. It only reports — it changes "
            "nothing — so act on what it returns: search again for what is "
            "unbacked, or state the gap in your final answer."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "components": {
                    "type": "array",
                    "description": "The breakdown calculate_estimate returned, as it returned it.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "estimated_hours": {
                                "type": "number",
                                "description": "The hours calculate_estimate assigned to it.",
                            },
                            "reference_amounts": {
                                "type": "array",
                                "items": {"type": "number"},
                            },
                        },
                        "required": ["name", "estimated_hours", "reference_amounts"],
                        "additionalProperties": False,
                    },
                },
                "total_hours": {
                    "type": "number",
                    "description": "The total_hours calculate_estimate returned.",
                },
            },
            "required": ["components", "total_hours"],
            "additionalProperties": False,
        },
    },
]


@dataclass
class ToolResult:
    """What a tool call produced.

    ``output`` goes back to the model as the ``function_call_output`` (JSON, so it
    can read numbers back out); ``observation`` is the one-line human summary the
    trace shows. They are separate because the two audiences want different things:
    the model needs the data, the reader needs the gist.
    """

    output: str
    observation: str
    error: bool = False


# --- implementations --------------------------------------------------------


async def search_budgets(args: dict[str, Any], *, backend: BudgetSearchBackend) -> ToolResult:
    """Retrieve comparable historical items for one component."""
    parsed = SearchBudgetsArgs.model_validate(args)
    filters = parsed.filters
    items = await backend(
        parsed.query,
        sectors=filters.sectors if filters else None,
        year_min=filters.year_min if filters else None,
        year_max=filters.year_max if filters else None,
    )
    items = items[:_MAX_ITEMS_IN_OBSERVATION]

    if not items:
        # The hint goes in the OUTPUT, not the observation: the model reads the
        # output, the trace reads the observation. An empty result with no advice
        # is what sends an agent into a rephrase loop.
        return ToolResult(
            output=json.dumps(
                {
                    "items": [],
                    "count": 0,
                    "hint": (
                        "No comparable historical budget for this component. Try ONE "
                        "differently worded search; if that is also empty, the corpus "
                        "does not cover this work — pass it to calculate_estimate with "
                        "an empty reference_amounts so it is flagged as unbudgeted, and "
                        "say so in your final answer."
                    ),
                }
            ),
            observation=f"no comparable budgets for {parsed.query[:60]!r}",
        )

    hours = [i["estimated_hours"] for i in items if i.get("estimated_hours") is not None]
    summary = (
        f"{len(items)} items for {parsed.query[:60]!r} — "
        f"hours={[round(h) for h in hours]} "
        f"(closest distance {min(i['distance'] for i in items):.3f})"
    )
    return ToolResult(
        output=json.dumps({"items": items, "count": len(items)}, ensure_ascii=False),
        observation=summary,
    )


def calculate_estimate(args: dict[str, Any]) -> ToolResult:
    """Cost every component from its reference hours, then total. No LLM here.

    The central estimate is the MEDIAN of the reference hours, not the mean: the
    historical corpus mixes project sizes, and one oversized analogue would drag a
    mean well above anything comparable. With the two or three references a search
    returns, the median is the more honest middle.

    A component with no references is costed at 0 and flagged ``unbudgeted``.
    Inventing a number there would be the one failure mode this whole pipeline
    exists to avoid.
    """
    parsed = CalculateEstimateArgs.model_validate(args)
    breakdown: list[dict[str, Any]] = []
    total = 0.0

    for component in parsed.components:
        refs = component.reference_amounts
        if refs:
            hours = round(statistics.median(refs) * (1 + CONTINGENCY_FACTOR), 1)
            unbudgeted = False
        else:
            hours = 0.0
            unbudgeted = True
        total += hours
        breakdown.append(
            {
                "name": component.name,
                "reference_count": len(refs),
                "estimated_hours": hours,
                "unbudgeted": unbudgeted,
            }
        )

    total = round(total, 1)
    unbudgeted_names = [c["name"] for c in breakdown if c["unbudgeted"]]
    summary = f"total={total}h across {len(breakdown)} components"
    if unbudgeted_names:
        summary += f" — unbudgeted: {', '.join(unbudgeted_names)}"

    return ToolResult(
        output=json.dumps(
            {
                "components": breakdown,
                "total_hours": total,
                "contingency_factor": CONTINGENCY_FACTOR,
                "summary": summary,
            },
            ensure_ascii=False,
        ),
        observation=summary,
    )


def validate_estimate(args: dict[str, Any]) -> ToolResult:
    """Report on a finished estimate. Reports only — it never edits the numbers."""
    parsed = ValidateEstimateArgs.model_validate(args)
    issues: list[str] = []
    # Checked against the hours calculate_estimate PRODUCED, never re-derived from
    # the references. A second copy of the cost formula would make this guard
    # circular — it would agree with itself even if the formula were wrong — and
    # would silently drift the day one copy changes.
    reported_sum = round(sum(c.estimated_hours for c in parsed.components), 1)

    for component in parsed.components:
        if not component.reference_amounts:
            issues.append(f"{component.name}: no historical reference (unbudgeted)")
            continue
        hours = component.estimated_hours
        if hours < _MIN_PLAUSIBLE_HOURS or hours > _MAX_PLAUSIBLE_HOURS:
            issues.append(
                f"{component.name}: {hours}h is outside the plausible band "
                f"({_MIN_PLAUSIBLE_HOURS}-{_MAX_PLAUSIBLE_HOURS}h)"
            )

    # A cent of drift is rounding; anything more means the reported total is not
    # the sum of the parts it claims to add up.
    if abs(reported_sum - parsed.total_hours) > 0.5:
        issues.append(
            f"total mismatch: reported {parsed.total_hours}h, components sum to {reported_sum}h"
        )

    observation = (
        "estimate looks coherent" if not issues else f"{len(issues)} issue(s): " + "; ".join(issues)
    )
    return ToolResult(
        output=json.dumps({"ok": not issues, "issues": issues}, ensure_ascii=False),
        observation=observation,
    )


# --- dispatch ---------------------------------------------------------------


async def dispatch_tool(
    name: str, arguments: dict[str, Any], *, backend: BudgetSearchBackend
) -> ToolResult:
    """Run one tool call and return its result.

    Failures are returned to the model as the tool output instead of raising: a
    malformed argument or an empty corpus is something the agent can recover from
    by calling again, and crashing the loop would throw away every step before it.
    """
    try:
        if name == "search_budgets":
            return await search_budgets(arguments, backend=backend)
        if name == "calculate_estimate":
            return calculate_estimate(arguments)
        if name == "validate_estimate":
            return validate_estimate(arguments)
        return ToolResult(
            output=json.dumps({"error": f"unknown tool {name!r}"}),
            observation=f"unknown tool {name!r}",
            error=True,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the model, see docstring
        log.warning("agent_tool_failed", tool=name, error=str(exc))
        return ToolResult(
            output=json.dumps({"error": f"{type(exc).__name__}: {exc}"}),
            observation=f"tool failed: {type(exc).__name__}: {exc}",
            error=True,
        )
