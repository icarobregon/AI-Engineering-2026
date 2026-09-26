"""Una foto del corpus: cuánto hay indexado y si la búsqueda vectorial es barata.

Existe porque la pantalla «Corpus e índice» necesita enseñar el corpus ANTES y
DESPUÉS de una ampliación, y ninguna de las rutas que ya había sabe contar: la de
ingesta responde por documento y la de búsqueda responde por consulta.

``hnsw_indexed`` es el dato que no se adivina mirando las filas. Sin índice HNSW
sobre la columna de embeddings, una búsqueda vectorial es un *sequential scan*:
funciona con mil chunks y deja de funcionar con cien mil, sin avisar y sin error.
Se consulta a ``pg_indexes`` en vez de asumirlo porque el índice se crea en una
migración, y una migración puede no haberse aplicado.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.rag.retrieval.collections import COLLECTIONS, Collection
from app.generation.rag.store.models import DocumentRow


@dataclass(frozen=True)
class CollectionStat:
    collection: str
    documents: int
    chunks: int
    hnsw_indexed: bool


@dataclass(frozen=True)
class CorpusStats:
    collections: tuple[CollectionStat, ...]
    total_documents: int
    total_chunks: int


async def _hnsw_indexes(session: AsyncSession) -> set[str]:
    """Tablas que tienen al menos un índice HNSW, según el propio Postgres."""
    filas = await session.execute(
        text(
            "SELECT tablename FROM pg_indexes "
            "WHERE schemaname = current_schema() AND indexdef ILIKE '%USING hnsw%'"
        )
    )
    return {fila[0] for fila in filas}


async def collect(session: AsyncSession) -> CorpusStats:
    """Cuenta documentos y chunks por colección, y si cada tabla tiene HNSW."""
    con_hnsw = await _hnsw_indexes(session)

    stats: list[CollectionStat] = []
    for collection in Collection:
        modelo = COLLECTIONS[collection].model
        # Los documentos se cuentan DISTINTOS sobre los chunks, no sobre la tabla
        # `documents`: esa es común a las tres colecciones, así que contarla daría
        # el mismo número tres veces.
        fila = (
            await session.execute(
                select(
                    func.count(modelo.id),
                    func.count(func.distinct(modelo.document_id)),
                )
            )
        ).one()
        stats.append(
            CollectionStat(
                collection=collection.value,
                chunks=fila[0] or 0,
                documents=fila[1] or 0,
                hnsw_indexed=modelo.__tablename__ in con_hnsw,
            )
        )

    total_documentos = (
        await session.execute(select(func.count(DocumentRow.id)))
    ).scalar_one()

    return CorpusStats(
        collections=tuple(stats),
        total_documents=total_documentos or 0,
        total_chunks=sum(s.chunks for s in stats),
    )
