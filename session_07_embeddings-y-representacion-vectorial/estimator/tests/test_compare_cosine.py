"""Unit tests for the hand-rolled cosine similarity in scripts/compare.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_COMPARE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "compare.py"
_spec = importlib.util.spec_from_file_location("compare", _COMPARE_PATH)
compare = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare)


def test_identical_vectors() -> None:
    assert compare.cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_parallel_vectors() -> None:
    assert compare.cosine_similarity([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == pytest.approx(1.0)


def test_orthogonal_vectors() -> None:
    assert compare.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_opposite_vectors() -> None:
    assert compare.cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_zero_vector_returns_zero() -> None:
    assert compare.cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0
