#!/usr/bin/env python3
"""Session 16 — the evaluation harness: the golden set against the DEPLOYED service.

This is the opposite of the test suite, and the difference is the whole point.
CI doubles the model because CI tests *our code*; this calls the real model
because it evaluates *the model*. So it spends money, it is not deterministic,
and it must never gate an ordinary commit. It runs deliberately, against a
running system, and it leaves a report behind.

WHERE IT RUNS. Since Session 15 the AI service publishes no port: from the host
only the business backend is reachable. So the harness runs INSIDE the private
network — in a throwaway container, because ``evals/`` is deliberately NOT in the
production image (the Dockerfile copies ``app/``, ``alembic/``, ``data/`` and
``scripts/`` and nothing else, so ``docker compose exec ai-service`` cannot find
this module)::

    docker compose run --rm --no-deps \
      -v "$(pwd)/estimator/evals:/app/evals" \
      -e AI_SERVICE_URL=http://ai-service:8000 \
      -e GIT_SHA="$(git rev-parse --short HEAD)" \
      ai-service python -m evals.production.run_eval --target rag

That is not an obstacle to route around; it is the deployment boundary doing its
job. Neither ``-e`` is decoration: nothing sets ``AI_SERVICE_URL`` inside the AI
service's own container, so without it ``--base-url`` falls back to
``http://localhost:8000`` — itself, where no server is listening because the
command replaced it — and the container has no git, so without ``GIT_SHA`` the
report's provenance reads ``unknown``. The API key comes from the environment
the service already has, never from this file.

TWO TARGETS, ONE EXPECTATION. The golden set states every expectation in HOURS,
the unit the historical corpus speaks, plus the ``hours_per_day`` convention.
Each target converts:

* ``--target rag``   POST /v1/estimate/from-transcript → ``total_engineer_days``,
  multiplied by ``hours_per_day``. One shot, no human gate.
* ``--target graph`` POST /v1/estimate/graph → ``estimate.total_hours``, already
  in hours because the graph computes them in Python from the references it
  matched. It can also stop in front of a person, which is a third outcome and
  is recorded as such.

Grading the same transcripts through both is what makes the two architectures
comparable, and it is why a unit slip shows up as a clean factor rather than as
an unexplained miss.

Exit code is 0 only when every case passes, so the same file can later be wired
as a regression gate without being rewritten.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

EVAL_DIR = Path(__file__).resolve().parent
SERVICE_ROOT = EVAL_DIR.parent.parent
DEFAULT_GOLDEN_SET = EVAL_DIR / "golden_set.json"
DEFAULT_REPORTS_DIR = EVAL_DIR / "reports"

RAG_ENDPOINT = "/v1/estimate/from-transcript"
GRAPH_ENDPOINT = "/v1/estimate/graph"

# Both estimate routes are rate limited to 10/minute per API key. Staying at 8
# leaves room for the state read the graph target makes, instead of discovering
# the limit as a 429 halfway through a paid run.
MAX_CALLS_PER_MINUTE = 8

# A single RAG request can run up to three gpt-5 generations at GENERATION_TIMEOUT
# (600 s) each: the corrective retry for citations and the repair for coherence
# are both real paths, not theory. A graph run fans out over several agents. The
# default client deadline has to sit above the worst case or the harness reports
# a timeout where the service was still working.
DEFAULT_TIMEOUT_S = 1800.0

DIM, RESET, GREEN, RED, YELLOW = "\033[2m", "\033[0m", "\033[32m", "\033[31m", "\033[33m"


# --------------------------------------------------------------------------- #
# Golden set
# --------------------------------------------------------------------------- #


def load_golden_set(path: Path | str = DEFAULT_GOLDEN_SET) -> dict[str, Any]:
    """Load the golden set and refuse a malformed one loudly.

    The checks are deliberately strict. A set that silently lost its abstention
    case still produces a healthy-looking report, and a healthy-looking report
    that measures nothing is worse than no report at all.
    """
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = doc.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{path}: expected a non-empty 'cases' list")
    if not doc.get("hours_per_day"):
        raise ValueError(f"{path}: 'hours_per_day' is the unit convention and is required")

    seen: set[str] = set()
    for case in cases:
        case_id = case.get("id")
        if not case_id or case_id in seen:
            raise ValueError(f"{path}: missing or duplicated case id {case_id!r}")
        seen.add(case_id)
        # EstimateRequest enforces this server-side; failing here costs nothing,
        # failing there costs a round trip and a confusing 422.
        if len(case.get("transcript", "")) < 100:
            raise ValueError(f"{case_id}: the transcript must be at least 100 characters")
        if case.get("expect_abstention"):
            continue
        rango = case.get("acceptable_range_hours") or []
        if len(rango) != 2 or rango[0] > rango[1]:
            raise ValueError(f"{case_id}: an estimation case needs a valid acceptable_range_hours")

    if not any(c.get("expect_abstention") for c in cases):
        raise ValueError(f"{path}: the golden set must contain at least one abstention case")
    return doc


def corpus_index() -> dict[str, str]:
    """Map every historical document id to its sector.

    Read from the JSON the corpus was built from, which is what makes a cited
    ``document_id`` checkable: an id outside this map was not in the history, so
    the citation is fabricated. Only ``document_id`` survives a re-ingest — every
    other id in the response is a Postgres autoincrement key.
    """
    index: dict[str, str] = {}
    for name in ("task_corpus.json", "budgets_sample.json"):
        path = SERVICE_ROOT / "data" / name
        if not path.exists():
            continue
        for project in json.loads(path.read_text(encoding="utf-8")):
            index[project["budget_id"]] = project.get("client_metadata", {}).get(
                "sector", "unknown"
            )
    return index


# --------------------------------------------------------------------------- #
# Calling the service
# --------------------------------------------------------------------------- #


def build_headers() -> dict[str, str]:
    """The estimate routes authenticate with ``X-API-Key``; the key is environment."""
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("ESTIMATE_API_KEY") or os.environ.get("AI_SERVICE_TOKEN")
    if key:
        headers["X-API-Key"] = key
    return headers


def _post(client: httpx.Client, path: str, payload: dict, timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = client.post(path, json=payload, timeout=timeout)
    except httpx.HTTPError as exc:
        return {
            "status": 0,
            "body": {},
            "latency_ms": (time.perf_counter() - started) * 1000,
            "transport_error": f"{type(exc).__name__}: {exc}",
        }
    latency_ms = (time.perf_counter() - started) * 1000
    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text[:500]}
    return {"status": response.status_code, "body": body, "latency_ms": latency_ms}


def call_rag(client: httpx.Client, case: dict, *, timeout: float) -> dict[str, Any]:
    """One transcript through the single-shot RAG pipeline.

    NOTE the absence of ``idempotency_key``. Sending one would replay the stored
    estimate from a previous run: the request would look fast and free and the
    evaluation would measure nothing at all. Note also that an abstention is
    cached too, for 24 h, which is the same trap wearing a kinder face.
    """
    return _post(client, RAG_ENDPOINT, {"transcript": case["transcript"]}, timeout)


def call_graph(client: httpx.Client, case: dict, *, run_id: str, timeout: float) -> dict[str, Any]:
    """One transcript through the multi-agent graph, blocking until it settles.

    ``estimation_id`` is fresh per run on purpose: the graph answers a known
    thread with what it already decided instead of estimating twice, which is
    right for a retry and wrong for a measurement.
    """
    estimation_id = f"eval-{run_id}-{case['id']}"
    result = _post(
        client,
        GRAPH_ENDPOINT,
        {"transcript": case["transcript"], "estimation_id": estimation_id},
        timeout,
    )
    result["estimation_id"] = estimation_id
    # The references live in the run's state, not in the response. One cheap GET
    # buys the same citation check the RAG target gets for free.
    if result["status"] == 200:
        try:
            state = client.get(f"{GRAPH_ENDPOINT}/{estimation_id}/state", timeout=60)
            if state.status_code == 200:
                result["state"] = state.json().get("values", {})
        except httpx.HTTPError:
            pass
    return result


# --------------------------------------------------------------------------- #
# Reading an answer
# --------------------------------------------------------------------------- #


def _rag_reading(body: dict, hours_per_day: int) -> dict[str, Any]:
    """What the RAG response says, in the golden set's unit."""
    days = body.get("total_engineer_days")
    documents: list[str] = []
    for module in body.get("modules") or []:
        for task in module.get("tasks") or []:
            for source in task.get("sources") or []:
                document_id = source.get("document_id")
                if document_id:
                    documents.append(document_id)
    return {
        "predicted_hours": days * hours_per_day if days is not None else None,
        "raw_value": days,
        "raw_unit": "engineer_days",
        "confidence": body.get("confidence"),
        # The contract's own abstention: a null total alone does NOT mean the
        # system abstained — a run whose grounded lines carry no days yields the
        # same null with confidence 'medium'. Only the declared verdict counts.
        "abstained": body.get("confidence") == "insufficient" and days is None,
        "escalated": False,
        "documents": documents,
    }


def _graph_reading(body: dict, state: dict) -> dict[str, Any]:
    """What the graph run says, in hours, plus where it stopped."""
    estimate = body.get("estimate")
    if estimate is None and isinstance(body.get("review_payload"), dict):
        # A run paused in front of a person still carries its estimate: the
        # reviewer has to see a number to judge it.
        estimate = body["review_payload"].get("estimate")
    components = (estimate or {}).get("components") or []
    grounded = [c for c in components if c.get("grounded")]
    documents = [
        str(match.get("reference_budget_id", "")).split("/")[0]
        for match in (state.get("budget_matches") or [])
        if match.get("reference_budget_id")
    ]
    total = (estimate or {}).get("total_hours")
    escalated = body.get("status") == "awaiting_human_review"
    return {
        "predicted_hours": total if total else None,
        "raw_value": total,
        "raw_unit": "hours",
        "confidence": state.get("confidence"),
        "status": body.get("status"),
        # The graph's way of saying "I do not know" is not a null: it is refusing
        # to answer on its own and handing the run to a person, or pricing
        # nothing because nothing matched.
        "abstained": bool(escalated or not grounded or not total),
        "escalated": escalated,
        "components": len(components),
        "grounded_components": len(grounded),
        "documents": documents,
    }


def evaluate_case(
    case: dict, result: dict, *, target: str, hours_per_day: int, corpus: dict[str, str]
) -> dict[str, Any]:
    """Compare one answer against what we decided beforehand a good one looks like."""
    body = result["body"] if isinstance(result.get("body"), dict) else {}
    base: dict[str, Any] = {
        "id": case["id"],
        "difficulty": case.get("difficulty", "unknown"),
        "sector": case.get("sector"),
        "http_status": result["status"],
        "latency_ms": round(result["latency_ms"], 1),
    }

    if result["status"] != 200:
        detail = result.get("transport_error") or str(body)[:300]
        return {**base, "type": "error", "passed": False, "detail": detail}

    reading = (
        _rag_reading(body, hours_per_day)
        if target == "rag"
        else _graph_reading(body, result.get("state") or {})
    )
    base.update(
        {k: reading[k] for k in ("confidence", "predicted_hours", "raw_value", "raw_unit")}
    )
    base["escalated"] = reading["escalated"]
    base["sources"] = _source_verdict(reading["documents"], case, corpus)

    if case.get("expect_abstention"):
        passed = reading["abstained"]
        return {
            **base,
            "type": "abstention",
            "passed": passed,
            "detail": (
                "abstained correctly"
                if passed
                else f"answered {reading['predicted_hours']} h "
                f"(confidence={reading['confidence']!r})"
            ),
        }

    low, high = case["acceptable_range_hours"]
    predicted = reading["predicted_hours"]
    within = predicted is not None and low <= predicted <= high
    expected = case.get("expected_hours")
    return {
        **base,
        "type": "estimation",
        "passed": within,
        "expected_hours": expected,
        "acceptable_range_hours": [low, high],
        "abs_error_hours": abs(predicted - expected) if predicted is not None else None,
        # The factor is what makes a unit slip legible: a system that copied the
        # corpus's hours into a field named days lands at ~8x, not at "high".
        "ratio_to_expected": round(predicted / expected, 2)
        if predicted and expected
        else None,
        "detail": (
            "within range"
            if within
            else f"{predicted} h outside [{low}, {high}]"
            if predicted is not None
            else f"no figure (confidence={reading['confidence']!r})"
        ),
    }


def _source_verdict(documents: list[str], case: dict, corpus: dict[str, str]) -> dict[str, Any]:
    """Do the cited documents exist, and are they from the right history?

    Two different failures. A cited id that is not in the corpus is a fabricated
    source — the hallucination the accuracy rate cannot see. An id that exists
    but belongs to another sector is weak evidence, not a lie, so it is counted
    apart.
    """
    unique = sorted(set(d for d in documents if d))
    unknown = [d for d in unique if d not in corpus]
    expected_sectors = set(case.get("expected_source_sectors") or [])
    on_sector = [d for d in unique if corpus.get(d) in expected_sectors] if expected_sectors else []
    return {
        "cited": len(unique),
        "fabricated": unknown,
        "budgets": len([d for d in unique if d.startswith("BUD-")]),
        "tasks": len([d for d in unique if d.startswith("TASK-")]),
        "on_expected_sector": len(on_sector),
        "sector_match_rate": round(len(on_sector) / len(unique), 2) if unique else None,
    }


# --------------------------------------------------------------------------- #
# Aggregating
# --------------------------------------------------------------------------- #


def summarise(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    """The headline metrics. Every one of them answers a different way of failing."""
    estimations = [e for e in evaluations if e["type"] == "estimation"]
    abstentions = [e for e in evaluations if e["type"] == "abstention"]
    errors = [e["abs_error_hours"] for e in estimations if e.get("abs_error_hours") is not None]
    latencies = [e["latency_ms"] for e in evaluations]
    fabricated = sum(len(e.get("sources", {}).get("fabricated") or []) for e in evaluations)
    cited = sum(e.get("sources", {}).get("cited", 0) for e in evaluations)

    return {
        "within_range_rate": (
            len([e for e in estimations if e["passed"]]) / len(estimations)
            if estimations
            else None
        ),
        "mean_absolute_error_hours": (sum(errors) / len(errors)) if errors else None,
        # ``all([])`` is True, which would report a set with no abstention case as
        # safe. load_golden_set refuses such a set; this stays explicit anyway.
        "abstention_correct": (
            all(e["passed"] for e in abstentions) if abstentions else None
        ),
        "mean_latency_ms": (sum(latencies) / len(latencies)) if latencies else None,
        "p95_latency_ms": _percentile(latencies, 95),
        "error_rate": len([e for e in evaluations if e["type"] == "error"]) / len(evaluations),
        "hallucinated_sources": fabricated,
        "hallucination_rate": round(fabricated / cited, 3) if cited else None,
        "escalated": len([e for e in evaluations if e.get("escalated")]),
        "cases_total": len(evaluations),
        "cases_passed": len([e for e in evaluations if e["passed"]]),
    }


def _percentile(values: list[float], pct: int) -> float | None:
    """Nearest-rank percentile, spelled out because ``statistics.quantiles`` needs
    at least two points and a seven-case run can legitimately be filtered to one."""
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 1)
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(round(pct / 100 * len(ordered) + 0.5))))
    return round(ordered[rank - 1], 1)


# --------------------------------------------------------------------------- #
# Running
# --------------------------------------------------------------------------- #


def _throttle(call_times: list[float]) -> None:
    """Stay under the endpoint's 10/minute budget."""
    recent = [t for t in call_times if time.monotonic() - t < 60]
    if len(recent) >= MAX_CALLS_PER_MINUTE:
        wait = 60 - (time.monotonic() - recent[0]) + 1
        if wait > 0:
            print(f"{DIM}  rate limit: waiting {wait:.0f}s{RESET}", flush=True)
            time.sleep(wait)


def _effective_retrieval(client: httpx.Client) -> dict[str, Any]:
    """The retrieval knobs AS THE SERVICE HAS THEM, not as ``.env`` describes them.

    Search mode, reranking and the stage toggles are resolved from the Redis
    runtime config first, so the Settings screen can change what every case
    retrieves without a single line moving in the repository. Reading them from
    the environment would put a plausible lie in the report's provenance, which
    is worse than the honest ``unavailable`` this falls back to.
    """
    try:
        response = client.get("/api/v1/config/retrieval", timeout=15)
        if response.status_code != 200:
            return {"source": f"unavailable (HTTP {response.status_code})"}
        knobs = response.json().get("retrieval") or {}
    except (httpx.HTTPError, ValueError) as exc:
        return {"source": f"unavailable ({type(exc).__name__})"}
    return {
        "source": "live config",
        **{name: knob.get("effective") for name, knob in knobs.items()},
        "overridden_at_runtime": sorted(n for n, k in knobs.items() if k.get("overridden")),
    }


def _run_meta(target: str, base_url: str, doc: dict, client: httpx.Client) -> dict[str, Any]:
    """What this run was measured against.

    Without it a report is a number with no provenance, and two reports cannot be
    compared: a drop in the accuracy rate means nothing if the model, the prompt
    or the retrieval mode moved underneath.
    """
    def _git(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", *args], cwd=SERVICE_ROOT, capture_output=True, text=True, timeout=5
            ).stdout.strip()
        except Exception:  # noqa: BLE001 — provenance must never fail a run
            return "unknown"

    return {
        "target": target,
        "base_url": base_url,
        "endpoint": RAG_ENDPOINT if target == "rag" else GRAPH_ENDPOINT,
        "git_sha": os.environ.get("GIT_SHA") or _git("rev-parse", "--short", "HEAD") or "unknown",
        "hours_per_day": doc["hours_per_day"],
        # These four have no runtime override: the environment IS the authority.
        "models": {
            "reformulation": os.environ.get("REFORMULATION_MODEL", "unknown"),
            "generation": os.environ.get("GENERATION_MODEL", "unknown"),
            "generation_reasoning_effort": os.environ.get(
                "GENERATION_REASONING_EFFORT", "unknown"
            ),
            "graph_supervisor": os.environ.get("GRAPH_SUPERVISOR_MODEL", "unknown"),
        },
        "retrieval": _effective_retrieval(client),
    }


def run(
    cases: list[dict], *, target: str, base_url: str, doc: dict, timeout: float
) -> dict[str, Any]:
    corpus = corpus_index()
    run_id = uuid.uuid4().hex[:8]
    evaluations: list[dict[str, Any]] = []
    call_times: list[float] = []
    started_at = datetime.now(timezone.utc)

    with httpx.Client(base_url=base_url.rstrip("/"), headers=build_headers()) as client:
        meta = _run_meta(target, base_url, doc, client)
        for index, case in enumerate(cases, start=1):
            _throttle(call_times)
            print(f"{DIM}[{index}/{len(cases)}] {case['id']}…{RESET}", flush=True)
            call_times.append(time.monotonic())
            result = (
                call_rag(client, case, timeout=timeout)
                if target == "rag"
                else call_graph(client, case, run_id=run_id, timeout=timeout)
            )
            evaluation = evaluate_case(
                case,
                result,
                target=target,
                hours_per_day=doc["hours_per_day"],
                corpus=corpus,
            )
            evaluations.append(evaluation)
            print("  " + _format_row(evaluation), flush=True)

    return {
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "meta": meta,
        "metrics": summarise(evaluations),
        "cases": evaluations,
    }


def _format_row(ev: dict[str, Any]) -> str:
    mark = f"{GREEN}PASS{RESET}" if ev["passed"] else f"{RED}FAIL{RESET}"
    extra = ""
    if ev.get("ratio_to_expected"):
        extra = f"  {DIM}x{ev['ratio_to_expected']}{RESET}"
    if ev.get("escalated"):
        extra += f"  {YELLOW}escalado{RESET}"
    fabricated = (ev.get("sources") or {}).get("fabricated") or []
    if fabricated:
        extra += f"  {RED}fuentes inventadas: {len(fabricated)}{RESET}"
    return f"{mark}  {ev['type']:11s} {ev['detail']}{extra}  {DIM}{ev['latency_ms']/1000:.0f}s{RESET}"


def _print_report(report: dict[str, Any]) -> None:
    m = report["metrics"]

    def fmt(value: Any, suffix: str = "", pct: bool = False) -> str:
        if value is None:
            return f"{YELLOW}n/d{RESET}"
        if isinstance(value, bool):
            return f"{GREEN}sí{RESET}" if value else f"{RED}no{RESET}"
        return f"{value * 100:.0f}%" if pct else f"{value:.1f}{suffix}"

    print(f"\n{DIM}Métricas ({report['meta']['target']}){RESET}")
    print(f"  within_range_rate          {fmt(m['within_range_rate'], pct=True)}")
    print(f"  mean_absolute_error_hours  {fmt(m['mean_absolute_error_hours'], ' h')}")
    print(f"  abstention_correct         {fmt(m['abstention_correct'])}")
    print(f"  mean_latency_ms            {fmt(m['mean_latency_ms'], ' ms')}")
    print(f"  p95_latency_ms             {fmt(m['p95_latency_ms'], ' ms')}")
    print(f"  error_rate                 {fmt(m['error_rate'], pct=True)}")
    print(f"  hallucination_rate         {fmt(m['hallucination_rate'], pct=True)}")
    print(f"\n{m['cases_passed']}/{m['cases_total']} casos pasan")


def save_report(report: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = re.sub(r"[:\-]", "", report["started_at"]).split(".")[0]
    path = out_dir / f"eval-{report['meta']['target']}-{stamp}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--target", choices=("rag", "graph"), default="rag")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("EVAL_BASE_URL")
        or os.environ.get("AI_SERVICE_URL")
        or "http://localhost:8000",
    )
    parser.add_argument("--golden-set", default=str(DEFAULT_GOLDEN_SET))
    parser.add_argument("--out", default=str(DEFAULT_REPORTS_DIR))
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N cases")
    parser.add_argument("--case", default=None, help="Run a single case by id")
    args = parser.parse_args(argv)

    doc = load_golden_set(args.golden_set)
    cases = doc["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            print(f"{RED}no hay ningún caso con id {args.case!r}{RESET}", file=sys.stderr)
            return 2
    if args.limit:
        cases = cases[: args.limit]

    endpoint = RAG_ENDPOINT if args.target == "rag" else GRAPH_ENDPOINT
    print(f"Evaluación — {len(cases)} caso(s) contra {args.base_url}{endpoint}")
    if "X-API-Key" not in build_headers():
        print(f"{YELLOW}  sin ESTIMATE_API_KEY: todo contestará 401{RESET}")

    report = run(
        cases, target=args.target, base_url=args.base_url, doc=doc, timeout=args.timeout
    )
    _print_report(report)

    path = save_report(report, Path(args.out))
    print(f"{DIM}informe → {path}{RESET}")

    return 0 if report["metrics"]["cases_passed"] == report["metrics"]["cases_total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
