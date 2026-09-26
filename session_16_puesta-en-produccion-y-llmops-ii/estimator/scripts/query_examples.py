#!/usr/bin/env python3
"""Semantic-search smoke test against the persisted corpus (Session 8).

Replaces ``compare.py``'s role: instead of measuring similarity between two
loose texts, it exercises the real retrieval path — HTTP against
``POST /embeddings/ingest`` and ``POST /search`` — with five queries that probe
the corpus from different angles (direct match, semantic reformulation,
out-of-domain, ambiguous, highly specific).

Idempotent: it first ingests ``data/budgets_sample.json`` (one document per
budget); documents already persisted answer 409 and are skipped, so re-running
the script never duplicates data.

Usage::

    # stack up first: docker compose up -d
    docker compose run --rm estimator python scripts/query_examples.py

    # or from the host (with the API on localhost:8000):
    uv run python scripts/query_examples.py

The base URL is taken from ``ESTIMATOR_API_BASE_URL`` if set; otherwise the script
probes ``http://localhost:8000`` and ``http://ai-service:8000`` (the compose
network alias) via ``GET /health``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# El `.env` del servicio, si lo hay. A nivel de módulo porque las claves se leen
# desde varias funciones. Dos detalles que importan:
#
# - Se le pasa la RUTA. `load_dotenv()` a secas busca desde el directorio de
#   trabajo, así que lanzar el script desde cualquier sitio que no fuera
#   `estimator/` no encontraba nada y la variable salía vacía sin decirlo.
# - NO pisa lo que ya exista en el entorno, así que dentro del contenedor sigue
#   mandando lo que pone compose. Desde el host deja de hacer falta exportar
#   nada: hasta ahora se mandaba una `X-API-Key` VACÍA aunque la clave estuviera
#   en el `.env` de al lado, y el fallo era un 401 sin explicación.
load_dotenv(ROOT / ".env")
CORPUS_PATH = ROOT / "data" / "budgets_sample.json"

CANDIDATE_BASE_URLS = ("http://localhost:8000", "http://ai-service:8000")

# Five angles on the same corpus — see the exercise statement.
QUERIES: list[tuple[str, str]] = [
    (
        "Componente directo conocido (sanity check)",
        "REST API development with JWT authentication for financial sector",
    ),
    (
        "Reformulación semántica (mismo concepto, otro vocabulario)",
        "secure backend service with token-based access control for banking applications",
    ),
    (
        "Dominio distinto (no debería estar en el corpus)",
        "mobile application for restaurant reservations",
    ),
    (
        "Consulta ambigua (sin match dominante)",
        "integration with external system",
    ),
    (
        "Consulta muy específica (vocabulario técnico preciso)",
        "migration from monolith to microservices architecture using Kubernetes",
    ),
]

TOP_K = 5
CONTENT_PREVIEW_CHARS = 120


def resolve_base_url(client: httpx.Client) -> str:
    """Honour ESTIMATOR_API_BASE_URL; otherwise probe the usual suspects."""
    explicit = os.environ.get("ESTIMATOR_API_BASE_URL")
    candidates = (explicit,) if explicit else CANDIDATE_BASE_URLS
    for base_url in candidates:
        try:
            if client.get(f"{base_url}/health").status_code == 200:
                return base_url
        except httpx.TransportError:
            continue
    print(
        "ERROR: no estimator API reachable. Start the stack (docker compose up -d) "
        "or set ESTIMATOR_API_BASE_URL.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def _service_headers() -> dict[str, str]:
    """La cabecera que exigen las rutas cerradas del servicio IA.

    ``/embeddings/ingest`` dejo de ser anonima: escribe en el corpus. La clave se
    lee del entorno —dentro del contenedor la pone compose— y se manda vacia si no
    esta, para que el fallo sea un 401 claro y no un KeyError a mitad de la siembra.
    """
    return {"X-API-Key": os.getenv("ESTIMATE_API_KEY", "")}


def _retrieval_headers() -> dict[str, str]:
    """``/search`` lleva la clave de RETRIEVAL, no la de estimacion.

    Este script hace las dos cosas —siembra y consulta—, asi que necesita las dos
    claves. Si solo hay una configurada, ``RETRIEVAL_API_KEY`` cae a la de
    estimacion, que es el mismo apano que hace compose.
    """
    clave = os.getenv("RETRIEVAL_API_KEY") or os.getenv("ESTIMATE_API_KEY", "")
    return {"X-API-Key": clave}


def ingest_corpus(client: httpx.Client, base_url: str) -> None:
    """One document per budget; 409 means already ingested (idempotent)."""
    budgets = json.loads(CORPUS_PATH.read_text())
    created, skipped = 0, 0
    for budget in budgets:
        response = client.post(
            f"{base_url}/embeddings/ingest",
            headers=_service_headers(),
            json={
                "source_path": f"data/budgets_sample.json::{budget['budget_id']}",
                "document_type": "historical_budget",
                "content": budget,
            },
        )
        if response.status_code == 200:
            created += 1
        elif response.status_code == 409:
            skipped += 1
        else:
            print(
                f"ERROR ingesting {budget['budget_id']}: "
                f"{response.status_code} {response.text[:200]}",
                file=sys.stderr,
            )
            raise SystemExit(1)

    print(f"Corpus: {len(budgets)} budgets — {created} ingested, {skipped} already present.")


def run_queries(client: httpx.Client, base_url: str) -> None:
    for index, (label, query) in enumerate(QUERIES, start=1):
        response = client.post(
            f"{base_url}/search",
            headers=_retrieval_headers(),
            json={"query": query, "k": TOP_K},
        )
        response.raise_for_status()
        body = response.json()

        print()
        print(f"[{index}/5] {label}")
        print(f'    query: "{query}"')
        print(f"    search_time_ms: {body['search_time_ms']}")
        print(f"    {'chunk_id':>8}  {'distance':>8}  {'chunk_type':<18}  content")
        for hit in body["results"]:
            preview = " ".join(hit["content"].split())[:CONTENT_PREVIEW_CHARS]
            print(
                f"    {hit['chunk_id']:>8}  {hit['distance']:>8.4f}  "
                f"{hit['chunk_type']:<18}  {preview}"
            )


def main() -> int:
    with httpx.Client(timeout=120.0) as client:
        base_url = resolve_base_url(client)
        print(f"Estimator API: {base_url}")
        ingest_corpus(client, base_url)
        run_queries(client, base_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
