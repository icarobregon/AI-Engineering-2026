"""Jinja2-based loader for versioned prompt templates."""

import hashlib
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.logging import get_logger
from app.prompts.references import load_reference_projects
from app.schemas.estimation import EstimationRequest

log = get_logger(__name__)

PROMPTS_DIR = Path(__file__).parent

_env = Environment(
    loader=FileSystemLoader(PROMPTS_DIR),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=False,
    undefined=StrictUndefined,
)


def render_estimation_prompt(
    request: EstimationRequest,
    version: str = "v1",
) -> tuple[str, str]:
    """Render the (system, user) pair for the estimation prompt at the given version."""
    system_tpl = _env.get_template(f"estimation/{version}/system.j2")
    user_tpl = _env.get_template(f"estimation/{version}/user.j2")

    references = load_reference_projects(request.project_type)
    context = {
        "project_type": request.project_type.value,
        "detail_level": request.detail_level.value,
        "output_format": request.output_format.value,
        "description": request.description,
        "reference_projects": references,
    }

    system = system_tpl.render(**context)
    user = user_tpl.render(**context)
    prompt_hash = hashlib.sha256((system + user).encode("utf-8")).hexdigest()[:12]

    log.info(
        "prompt_rendered",
        version=version,
        prompt_hash=prompt_hash,
        num_references=len(references),
        project_type=request.project_type.value,
        detail_level=request.detail_level.value,
        output_format=request.output_format.value,
    )

    return system, user
