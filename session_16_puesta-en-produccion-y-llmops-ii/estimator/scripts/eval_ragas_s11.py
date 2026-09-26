#!/usr/bin/env python3
"""Measure GENERATION quality with RAGAS over the Session 11 golden set.

Runs the five estimation queries of ``evals/golden_retrieval.json`` (Q1–Q5, the
budget-only project descriptions) through the real retrieval + generation path and
scores the result with the four RAGAS metrics, reporting one row per query plus the
mean. Q6–Q8 are skipped on purpose: they are cross-collection QA questions, not
estimation requests, and carry no reference estimate.

The four metrics split into two pairs. ``faithfulness`` and ``answer_relevancy``
grade the GENERATION (is the estimate supported by the context it was given, does it
answer what was asked); ``context_precision`` and ``context_recall`` grade the
RETRIEVAL (was what we retrieved relevant, did it bring everything the reference
answer needs). Reading one without the others is how a system gets tuned into
looking good on a metric while getting worse at its job.

Method notes:
* The queries of the golden set are already distilled briefs, so the reformulation
  stage is skipped and the brief is used as the ``EstimationQuery`` directly — the
  same shortcut the degraded path in ``query_reformulator`` takes. Everything after
  that (embedding, retrieval, truncation, context assembly, generation) runs with
  the SAME calls and the same settings the orchestrator uses.
* ``contexts`` are the chunks that actually reached the prompt (post token-budget
  truncation), not everything retrieval returned: scoring context precision against
  chunks the generator never saw would measure the wrong stage.
* The scored answer is the estimate AFTER ``enforce_citation_policy`` — what the
  service would serve. The citation report printed alongside describes what the
  model produced BEFORE that, so a dangling citation shows up in the report even
  though it can no longer reach the answer.
* Unlike ``estimate_from_transcript`` this harness does NOT run the corrective
  retry: measuring the first pass is what makes the citation report informative.

RAGAS version note: the API moves between minors. This is written against the
version pinned in ``pyproject.toml`` (ragas>=0.4.3), using the modern
``EvaluationDataset``/``SingleTurnSample`` schema with the classic metric objects,
which is the combination ``evaluate()`` accepts there — the ``ragas.metrics.collections``
classes are NOT accepted by ``evaluate()`` in this version.

Cost and runtime: five generations with ``GENERATION_MODEL`` (gpt-5 by default, at
``GENERATION_REASONING_EFFORT``) plus the judge calls of four metrics over five
samples with ``JUDGE_MODEL``. Expect single-digit minutes.

Usage (host, stack up + budgets ingested + OPENAI_API_KEY)::

    uv run python scripts/eval_ragas_s11.py

Ingest first if the corpus is empty: ``scripts/query_examples.py``.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.s08_common import require_embedder  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.dependencies import get_runtime_retrieval_config, get_token_encoder  # noqa: E402
from app.generation.rag.context_assembler import (  # noqa: E402
    build_context_block,
    truncate_to_token_budget,
)
from app.generation.rag.estimator import generate_estimate  # noqa: E402
from app.generation.rag.retrieval.pipeline import retrieve  # noqa: E402
from app.generation.rag.schemas import (  # noqa: E402
    CitationReport,
    Estimate,
    EstimationQuery,
    RetrievedChunk,
)
from app.generation.rag.validation import (  # noqa: E402
    enforce_citation_policy,
    verify_citations,
)

GOLDEN_PATH = ROOT / "evals" / "golden_retrieval.json"
# A judge distinct from (and cheaper than) the generator: sharing a model with the
# system under test means sharing its blind spots.
JUDGE_MODEL = "gpt-4o-mini"
# Only the budget-only project descriptions carry a reference estimate.
GRADED_QUERIES = 5
METRIC_NAMES = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")


def _estimate_as_text(estimate: Estimate) -> str:
    """Render an estimate as the prose RAGAS scores as the ``response``.

    Presentation for a single consumer, hence a private helper in the harness
    rather than anything the service exposes. Ungrounded lines are rendered
    explicitly as "no sufficient source data" instead of being dropped: how the
    system abstains is part of what is being measured.

    The rendering deliberately quotes the ``evidence`` and NOT the ``document_id``:
    a budget chunk's text carries the project and component names but not its
    ``BUD-2024-xxx`` id (see ``chunking/structural.py``), so a claim phrased as
    "derived from BUD-2024-001" is unverifiable against the very contexts the judge
    is given — it would measure the judge's ability to resolve identifiers instead
    of the system's grounding.
    """
    lines: list[str] = []
    if estimate.confidence == "insufficient":
        return (
            "No estimate could be produced from the retrieved context. "
            f"{estimate.insufficient_context_explanation or ''}".strip()
        )

    lines.append(f"Total: {estimate.total_engineer_days} engineer-days.")
    for module in estimate.modules:
        lines.append(f"\nModule {module.name}:")
        for task in module.tasks:
            if not task.grounded:
                lines.append(f"- {task.name}: no sufficient source data.")
                continue
            evidence = "; ".join(ref.evidence for ref in task.sources)
            lines.append(
                f"- {task.name}: {task.engineer_days} engineer-days, derived from: {evidence}"
            )
    if estimate.assumptions:
        lines.append("\nAssumptions: " + "; ".join(a.description for a in estimate.assumptions))
    lines.append(f"\nReasoning: {estimate.reasoning}")
    return "\n".join(lines)


async def _run_pipeline(
    query_text: str,
    embedder,
    settings,
) -> tuple[Estimate, list[RetrievedChunk], CitationReport]:
    """Retrieve, generate and apply the citation policy for one golden query.

    Returns the estimate the service would serve, the chunks that reached the
    prompt, and the per-line citation report of the raw generation.
    """
    query = EstimationQuery(function=query_text)
    query_embedding = await asyncio.to_thread(embedder.embed_one, query_text)

    # Same resolution order as the orchestrator: a runtime override in Redis wins
    # over the .env default, so the harness measures the configuration actually in
    # force rather than the one on disk.
    runtime = get_runtime_retrieval_config()
    retrieval = await retrieve(
        query_embedding=query_embedding,
        query_text=query_text,
        search_mode=runtime.effective_search_mode(),
        rerank=runtime.effective_rerank(),
        top_k=settings.RETRIEVAL_TOP_K,
        recall_k=settings.RETRIEVAL_RECALL_TOP_K,
        rerank_top_n=settings.RERANK_TOP_N,
        distance_threshold=settings.RETRIEVAL_DISTANCE_THRESHOLD,
        rrf_k=settings.RRF_K,
    )
    kept = truncate_to_token_budget(
        retrieval.chunks, settings.MAX_CONTEXT_TOKENS, get_token_encoder()
    )
    estimate = await generate_estimate(build_context_block(kept), structured_query=query)
    report = verify_citations(estimate, kept)
    return enforce_citation_policy(estimate, kept), kept, report


def _score(rows: list[dict], settings) -> list[dict[str, float]]:
    """Run RAGAS over the collected rows and return the per-row metric scores."""
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (
        answer_relevancy,
        context_precision,
        context_recall,
        faithfulness,
    )

    judge = LangchainLLMWrapper(ChatOpenAI(model=JUDGE_MODEL, api_key=settings.OPENAI_API_KEY))
    embeddings = LangchainEmbeddingsWrapper(
        OpenAIEmbeddings(model=settings.EMBEDDING_MODEL, api_key=settings.OPENAI_API_KEY)
    )

    dataset = EvaluationDataset(
        samples=[
            SingleTurnSample(
                user_input=row["question"],
                retrieved_contexts=row["contexts"],
                response=row["answer"],
                reference=row["ground_truth"],
            )
            for row in rows
        ]
    )
    result = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        llm=judge,
        embeddings=embeddings,
    )
    return [{name: float(scores[name]) for name in METRIC_NAMES} for scores in result.scores]


def _print_report(rows: list[dict], scores: list[dict[str, float]]) -> None:
    """Print the deliverables: the RAGAS table and the citation verification."""
    print("\n## RAGAS — generation quality over the Session 11 golden set\n")
    print("| Query | " + " | ".join(METRIC_NAMES) + " |")
    print("| --- | " + " | ".join("---" for _ in METRIC_NAMES) + " |")
    for row, score in zip(rows, scores):
        cells = " | ".join(f"{score[name]:.2f}" for name in METRIC_NAMES)
        print(f"| {row['id']} | {cells} |")
    means = " | ".join(
        f"**{statistics.fmean(score[name] for score in scores):.2f}**" for name in METRIC_NAMES
    )
    print(f"| **Average** | {means} |")

    print("\n## Citation verification (raw generation, before the policy is applied)\n")
    print("| Query | lines | grounded | dangling | insufficient | dangling ids |")
    print("| --- | --- | --- | --- | --- | --- |")
    for row in rows:
        report: CitationReport = row["report"]
        ids = ", ".join(str(i) for i in report.dangling_source_ids) or "—"
        print(
            f"| {row['id']} | {len(report.lines)} | {report.grounded} | "
            f"{report.dangling} | {report.insufficient} | {ids} |"
        )

    print("\n### Per-line detail\n")
    for row in rows:
        print(f"**{row['id']}** — {row['served_total']}")
        for line in row["report"].lines:
            cited = ", ".join(str(i) for i in line.cited_chunk_ids) or "—"
            print(f"- [{line.status}] {line.module} › {line.task} (cites {cited})")
        print()


async def main() -> int:
    settings = get_settings()
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    queries = [q for q in golden["queries"] if "ground_truth" in q][:GRADED_QUERIES]
    if len(queries) < GRADED_QUERIES:
        print(
            f"Expected {GRADED_QUERIES} queries with a ground_truth in {GOLDEN_PATH.name}, "
            f"found {len(queries)}.",
            file=sys.stderr,
        )
        return 1

    embedder = require_embedder()

    rows: list[dict] = []
    for query in queries:
        print(f"Running {query['id']}...", file=sys.stderr)
        estimate, kept, report = await _run_pipeline(query["query"], embedder, settings)
        if not kept:
            print(
                f"{query['id']} retrieved nothing — is the budget corpus ingested? "
                "Run scripts/query_examples.py.",
                file=sys.stderr,
            )
            return 1
        rows.append(
            {
                "id": query["id"],
                "question": query["query"],
                "answer": _estimate_as_text(estimate),
                "contexts": [chunk.content for chunk in kept],
                "ground_truth": query["ground_truth"],
                "report": report,
                "served_total": (
                    f"{estimate.total_engineer_days} engineer-days"
                    if estimate.total_engineer_days is not None
                    else f"no total ({estimate.confidence})"
                ),
            }
        )

    print("Scoring with RAGAS...", file=sys.stderr)
    _print_report(rows, _score(rows, settings))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
