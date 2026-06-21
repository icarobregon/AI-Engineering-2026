"""Jinja2 loader for versioned prompt templates.

The on-disk layout is ``app/prompts/<use_case>/<version>/<role>.j2``. Versioning
is required from day one: switching prompts becomes a string change at the
call site (``version="v2"``), not a code refactor.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.schemas.estimation import EstimationRequest
from app.sessions import ProjectMetadata

_BASE_DIR = Path(__file__).resolve().parent

_env = Environment(
    loader=FileSystemLoader(_BASE_DIR),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
    keep_trailing_newline=True,
)


def render_estimation_prompt(
    request: EstimationRequest,
    version: str = "v1",
) -> tuple[str, str]:
    """Render the system and user prompts for the estimation use case.

    Returns:
        A tuple ``(system_prompt, user_prompt)`` ready to be sent to the LLM
        as separate ``role: "system"`` and ``role: "user"`` messages.
    """
    context = {
        "description": request.description,
        "project_type": request.project_type.value,
        "detail_level": request.detail_level.value,
        "output_format": request.output_format.value,
    }
    system = _env.get_template(f"estimation/{version}/system.j2").render(**context)
    user = _env.get_template(f"estimation/{version}/user.j2").render(**context)
    return system, user


def render_estimation_prompt_with_metadata(
    request: EstimationRequest,
    project_metadata: ProjectMetadata,
    version: str = "v2",
) -> tuple[str, str]:
    """Render estimation prompts (v2+) including the project_metadata block.

    The template receives ``project_metadata`` as a Pydantic object and
    ``project_metadata_empty`` as a boolean so the template can skip the
    ``<project_metadata>`` block entirely on the first turn.
    """
    context = {
        "description": request.description,
        "project_type": request.project_type.value,
        "detail_level": request.detail_level.value,
        "output_format": request.output_format.value,
        "project_metadata": project_metadata,
        "project_metadata_empty": project_metadata.is_empty(),
    }
    system = _env.get_template(f"estimation/{version}/system.j2").render(**context)
    user = _env.get_template(f"estimation/{version}/user.j2").render(**context)
    return system, user


def render_metadata_prompt(user_message: str, version: str = "v1") -> tuple[str, str]:
    """Render the system and user prompts for the metadata-extraction LLM call."""
    context = {"user_message": user_message}
    system = _env.get_template(f"metadata/{version}/system.j2").render(**context)
    user = _env.get_template(f"metadata/{version}/user.j2").render(**context)
    return system, user
