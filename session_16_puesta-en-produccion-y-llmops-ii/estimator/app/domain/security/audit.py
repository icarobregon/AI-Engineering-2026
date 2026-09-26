"""Every tool call an agent makes, through one chokepoint, in the log.

The test this file is written against: given only the log of a run, can you say
what each agent did, with what, and what came back? If yes, an incident is a
query. If no, it is an archaeology project.

**Denied actions are the most valuable lines here.** A successful call is
expected and mostly uninteresting; a denial is the system telling you an agent
tried something it was not allowed to do, which is either a wiring bug or the
model going somewhere you did not predict. They are logged at WARNING and they
carry the reason.

**Arguments are redacted, not omitted.** The shape of what was sent is what
makes a log line diagnosable; the transcript body inside it is client material
that has no business being in a log aggregator.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

import structlog

from app.domain.security.grants import TOOL_RISK
from app.domain.security.guard import ActionRequest, guard_action

log = structlog.get_logger()

# Long free text in an argument is the client's meeting, not a parameter worth
# storing. Keep enough to recognise the call, drop the rest.
_MAX_VALUE_CHARS = 120


class ActionDeniedError(RuntimeError):
    """The guard refused an action. Carries the reason it gave."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def redact_sensitive(args: dict[str, Any]) -> dict[str, Any]:
    """Keep the shape of the arguments, drop the payload inside them."""
    redacted: dict[str, Any] = {}
    for key, value in (args or {}).items():
        if isinstance(value, str):
            redacted[key] = (
                value if len(value) <= _MAX_VALUE_CHARS else f"{value[:_MAX_VALUE_CHARS]}…"
            )
        elif isinstance(value, list):
            redacted[key] = f"[{len(value)} item(s)]"
        elif isinstance(value, dict):
            redacted[key] = redact_sensitive(value)
        else:
            redacted[key] = value
    return redacted


def summarize(result: Any) -> str:
    """One line describing what came back, for the log."""
    observation = getattr(result, "observation", None)
    if isinstance(observation, str) and observation:
        return observation[:_MAX_VALUE_CHARS]
    return f"{type(result).__name__}"


async def execute_guarded(request: ActionRequest, tool: Callable[..., Awaitable[Any] | Any]) -> Any:
    """Validate ``request``, run ``tool``, and record both outcomes.

    ``tool`` is passed in rather than looked up: this module may not import
    ``app.generation`` (the tools' home is a sibling layer), and injecting the
    callable is what keeps the audit chokepoint usable from a test with no
    retrieval backend behind it.
    """
    decision = guard_action(request)
    risk = TOOL_RISK.get(request.tool)
    entry = log.bind(
        agent=request.agent,
        tool=request.tool,
        tool_risk=risk.value if risk else None,
        args=redact_sensitive(request.args),
        estimation_id=request.estimation_id,
        allowed=decision.allowed,
    )

    if not decision.allowed:
        entry.warning("action_denied", reason=decision.reason)
        raise ActionDeniedError(decision.reason)

    result = tool(**request.args)
    if hasattr(result, "__await__"):
        result = await result
    entry.info("action_executed", result_summary=summarize(result))
    return result
