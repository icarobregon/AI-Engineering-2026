"""Typed contracts for the Session 12 estimation agent.

Three groups of models, deliberately separated:

* **Tool arguments** — what the model is allowed to send us. The JSON Schemas the
  API enforces live in ``agent_tools.py``; these mirror them so the dispatcher
  validates the parsed arguments a second time, on our side, before any of it
  reaches the retrieval pipeline. The model is an untrusted caller.
* **Trace** — ``AgentStep`` / ``AgentTrace``: what the agent decided, what it did
  and what it saw, in order. This is half the exercise, so it is a first-class
  typed artefact rather than print statements scattered through the loop.
* **Result** — ``AgentEstimate``: the LIGHT estimate the agent produces. It is NOT
  the RAG ``Estimate`` of Session 9-11 (modules -> tasks, per-line citations,
  assumptions) and does not try to be: the agent reasons at component level, so a
  heavier schema would only invite it to invent detail it never retrieved.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# --- tool arguments (mirror of the JSON Schemas in agent_tools.py) -----------


class SearchFilters(BaseModel):
    """Optional metadata narrowing for one budget search."""

    sectors: list[str] | None = Field(
        default=None, description="Client sectors to restrict the search to."
    )
    year_min: int | None = Field(default=None, description="Oldest project year to consider.")
    year_max: int | None = Field(default=None, description="Newest project year to consider.")


class SearchBudgetsArgs(BaseModel):
    query: str
    filters: SearchFilters | None = None


class ComponentInput(BaseModel):
    """One component to cost, with the historical hours found for it."""

    name: str
    reference_amounts: list[float] = Field(default_factory=list)


class CalculateEstimateArgs(BaseModel):
    components: list[ComponentInput]


class CostedComponent(ComponentInput):
    """A component as calculate_estimate priced it — hours included."""

    estimated_hours: float


class ValidateEstimateArgs(BaseModel):
    components: list[CostedComponent]
    total_hours: float


# --- trace ------------------------------------------------------------------


class AgentStep(BaseModel):
    """One reason -> act -> observe cycle.

    ``reasoning`` is the model's own summary of why it chose this action (the
    Responses API reasoning summary), not our reconstruction. It is empty when the
    model returned no summary for that turn, which is normal at low effort.

    ``iteration`` is the turn this step came from. Several steps share a turn
    whenever the model asks for several tools at once — and therefore share one
    reasoning summary, since the model reasoned once and then fanned out.
    """

    step: int
    iteration: int = 0
    reasoning: str = ""
    tool: str
    arguments: dict = Field(default_factory=dict)
    observation: str = ""
    error: bool = False

    def render(self, reasoning_shown_at: int | None = None) -> str:
        """Render the step in the console format the exercise asks for.

        ``reasoning_shown_at`` is the step number that already printed this turn's
        reasoning in full. Repeating three paragraphs verbatim for every parallel
        call makes the trace unreadable, so the repeats point back instead — the
        text itself stays on the model, nothing is lost.
        """
        args = ", ".join(f"{k}={v!r}" for k, v in self.arguments.items())
        if reasoning_shown_at is not None:
            reasoning = f"(same turn as STEP {reasoning_shown_at} — the model reasoned once, then fanned out)"
        else:
            reasoning = self.reasoning or "(no summary returned)"
        lines = [
            f"STEP {self.step}",
            f"reasoning: {reasoning}",
            f"action: {self.tool}({args})",
            f"observation: {self.observation}",
        ]
        return "\n".join(lines)


class AgentTrace(BaseModel):
    """The ordered record of everything the agent did."""

    steps: list[AgentStep] = Field(default_factory=list)
    iterations: int = 0
    stop_reason: str = "natural"
    model: str = ""
    reasoning_effort: str = ""

    def render(self) -> str:
        header = (
            f"AGENT TRACE — model={self.model} effort={self.reasoning_effort} "
            f"iterations={self.iterations} stop={self.stop_reason}"
        )
        rendered = []
        first_of_turn: dict[int, int] = {}
        for step in self.steps:
            shown_at = first_of_turn.get(step.iteration)
            rendered.append(step.render(reasoning_shown_at=shown_at))
            first_of_turn.setdefault(step.iteration, step.step)
        body = "\n\n".join(rendered)
        return f"{header}\n{'=' * len(header)}\n\n{body}"


# --- result -----------------------------------------------------------------


class EstimatedComponent(BaseModel):
    name: str = Field(description="The component as the agent identified it in the transcript.")
    estimated_hours: float = Field(description="Engineer-hours for this component.")
    rationale: str = Field(description="Which historical budgets back this number, in one line.")
    grounded: bool = Field(
        description="False when no comparable historical budget was found and the "
        "number is not backed by retrieval."
    )


class AgentEstimate(BaseModel):
    """The agent's final answer. Kept small on purpose — see the module docstring."""

    project: str = Field(description="Short name of the project being estimated.")
    components: list[EstimatedComponent]
    total_hours: float = Field(description="Sum of the component hours, including contingency.")
    notes: str = Field(description="Caveats, gaps and anything the human should check.")
