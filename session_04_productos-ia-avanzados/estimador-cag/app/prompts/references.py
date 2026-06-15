"""Loader for server-side reference projects used to calibrate the model."""

import json
from functools import lru_cache
from pathlib import Path

from app.schemas.estimation import ProjectType, ReferenceProject

REFERENCES_FILE = Path(__file__).parent / "reference_projects.json"


@lru_cache(maxsize=1)
def _load_all() -> tuple[ReferenceProject, ...]:
    data = json.loads(REFERENCES_FILE.read_text())
    return tuple(ReferenceProject(**entry) for entry in data)


def load_reference_projects(project_type: ProjectType) -> list[ReferenceProject]:
    """Return reference projects matching the requested type (empty list if none)."""
    return [ref for ref in _load_all() if ref.project_type == project_type]
