"""Structural chunker for JSON budgets.

Rule: **one component = one chunk**. Each chunk's embeddable ``text`` combines a
context header from the parent budget (so an auth component from finance does not
compete in the index with an auth component from an unrelated sector) with the
component's own fields. Structured filter data goes into ``metadata`` and is NOT
embedded.

No overlap, no splitting of long descriptions: a component is assumed to fit in a
single chunk. An abnormally long description is left as a talking point for the
live session.
"""

from __future__ import annotations

import tiktoken

from app.embedding_pipeline.schemas import Budget, Chunk

# The index model. Token counting must match the model that will embed the text.
EMBEDDING_MODEL = "text-embedding-3-small"


class JSONStructuralChunker:
    def __init__(self, model: str = EMBEDDING_MODEL) -> None:
        self._encoding = tiktoken.encoding_for_model(model)

    def chunk(self, budgets: list[Budget]) -> list[Chunk]:
        chunks: list[Chunk] = []
        for budget in budgets:
            for component in budget.components:
                text = self._build_text(budget, component)
                chunks.append(
                    Chunk(
                        chunk_id=f"{budget.budget_id}::{component.component_id}",
                        text=text,
                        metadata={
                            "budget_id": budget.budget_id,
                            "component_id": component.component_id,
                            "client_sector": budget.client_metadata.sector,
                            "main_technology": budget.main_technology,
                            "year": budget.year,
                            "complexity": component.complexity,
                            "estimated_hours": component.estimated_hours,
                        },
                        token_count=len(self._encoding.encode(text)),
                    )
                )
        return chunks

    @staticmethod
    def _build_text(budget: Budget, component) -> str:
        """Context header from the parent budget + the component's own fields."""
        return (
            "# Project context\n"
            f"Project: {budget.project_summary}\n"
            f"Sector: {budget.client_metadata.sector}\n"
            f"Year: {budget.year}\n"
            f"Main technology: {budget.main_technology}\n"
            "\n# Component\n"
            f"Name: {component.name}\n"
            f"Description: {component.description}\n"
            f"Tech stack: {', '.join(component.tech_stack)}\n"
            f"Complexity: {component.complexity}\n"
            f"Estimated hours: {component.estimated_hours}"
        )
