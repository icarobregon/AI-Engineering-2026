"""Tests for app/context/examples.py."""

from app.context.examples import ESTIMATION_EXAMPLES, format_examples_for_prompt


def test_estimation_examples_is_non_empty_list():
    assert isinstance(ESTIMATION_EXAMPLES, list)
    assert len(ESTIMATION_EXAMPLES) > 0


def test_estimation_examples_have_required_keys():
    for example in ESTIMATION_EXAMPLES:
        assert "meeting_summary" in example, "Each example must have a 'meeting_summary' key"
        assert "estimation" in example, "Each example must have an 'estimation' key"


def test_estimation_examples_values_are_non_empty_strings():
    for i, example in enumerate(ESTIMATION_EXAMPLES):
        assert isinstance(example["meeting_summary"], str) and example["meeting_summary"].strip(), (
            f"Example {i} has an empty 'meeting_summary'"
        )
        assert isinstance(example["estimation"], str) and example["estimation"].strip(), (
            f"Example {i} has an empty 'estimation'"
        )


def test_format_examples_for_prompt_returns_string():
    result = format_examples_for_prompt(ESTIMATION_EXAMPLES)
    assert isinstance(result, str)
    assert len(result) > 0


def test_format_examples_for_prompt_contains_all_examples():
    result = format_examples_for_prompt(ESTIMATION_EXAMPLES)
    for i in range(1, len(ESTIMATION_EXAMPLES) + 1):
        assert f"--- EXAMPLE {i} ---" in result


def test_format_examples_for_prompt_contains_example_content():
    result = format_examples_for_prompt(ESTIMATION_EXAMPLES)
    first = ESTIMATION_EXAMPLES[0]
    assert first["meeting_summary"][:50] in result
    assert first["estimation"][:50] in result


def test_format_examples_for_prompt_empty_list():
    result = format_examples_for_prompt([])
    assert result == ""


def test_format_examples_for_prompt_single_example():
    single = [ESTIMATION_EXAMPLES[0]]
    result = format_examples_for_prompt(single)
    assert "--- EXAMPLE 1 ---" in result
    assert "--- EXAMPLE 2 ---" not in result
