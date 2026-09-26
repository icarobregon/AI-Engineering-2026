"""Una referencia histórica, entera: de dónde sale el número que la respalda.

El grafo guarda en ``budget_matches`` un ``reference_budget_id`` con la forma
``{budget_id}/{module}`` y el total de horas de ese módulo. Eso le basta al
estimador, pero no a la persona que valida: el revisor ve «79 h» y con eso solo
no puede saber si vienen de su sector, de hace cuatro años o de otro stack.

Aquí esa referencia se resuelve a las tareas que la componen. La suma de sus
horas ES el número que viajó en el match —comprobado sobre las 133 referencias
distintas de las ejecuciones guardadas: cuadran 133 de 133—, así que el desglose
no es un dato parecido, es la descomposición exacta de lo que se usó.

El nombre, la descripción y el stack de cada tarea existen SÓLO dentro del texto
del chunk: ``component_metadata`` no los copia a la metadata, y son justo los
tres campos que dicen si una referencia es comparable. Por eso hay que parsear el
texto, y por eso el parser vive pegado a ``render_component_text``, que es quien
lo escribe; un test recorre el renderizador y el parser en el mismo sentido, de
modo que cambiar el formato sin tocar esto rompe la suite en vez de vaciar la
pantalla en silencio.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Float, and_, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.rag.store.models import BudgetChunkRow

# El mismo valor con el que el buscador de presupuestos filtra (dependencies.py):
# las referencias que el grafo cita salen de ahí, así que resolverlas contra otro
# tipo de chunk devolvería un desglose que nadie usó.
CHUNK_TYPE = "historical_task"

_BUDGET_ID = BudgetChunkRow.metadata_["budget_id"].astext
_MODULE = BudgetChunkRow.metadata_["module"].astext


@dataclass(frozen=True)
class ReferenceTask:
    """Una tarea del módulo: la unidad que de verdad lleva horas."""

    component_id: str
    name: str
    description: str
    tech_stack: str
    complexity: str
    estimated_hours: float


@dataclass(frozen=True)
class Reference:
    """Un módulo de un presupuesto histórico, con su contexto y su desglose."""

    reference_budget_id: str
    budget_id: str
    module: str
    project: str
    client_sector: str
    year: int | None
    main_technology: str
    total_hours: float
    tasks: tuple[ReferenceTask, ...]


def split_reference(reference_budget_id: str) -> tuple[str, str] | None:
    """Separa ``{budget_id}/{module}`` en sus dos mitades.

    Parte por la PRIMERA barra, no por todas: hay un módulo que se llama
    «Frontend / UX» —115 chunks del corpus— y un ``split("/")`` lo partiría en
    tres trozos y no encontraría nada. El identificador nunca las lleva: ninguna
    fila del corpus tiene una barra en ``budget_id``, comprobado.
    """
    budget_id, sep, module = reference_budget_id.partition("/")
    if not sep or not budget_id or not module:
        return None
    return budget_id, module


def _campos_del_texto(content: str) -> dict[str, str]:
    """Lo que ``render_component_text`` escribió y la metadata no guarda.

    Línea a línea y por etiqueta exacta, en vez de una expresión regular sobre
    todo el bloque: una descripción que contenga «Tech stack:» a mitad de frase
    no puede así confundirse con el campo, porque sólo cuenta el primer dos
    puntos de la línea y ninguna etiqueta lleva uno dentro.

    Se parte por «:» y no por «: » a propósito: un componente sin stack hace que
    el renderizador escriba «Tech stack:» a secas, sin espacio, y con el
    separador largo ese campo desaparecía del resultado en lugar de salir vacío.
    """
    campos: dict[str, str] = {}
    for linea in content.splitlines():
        cruda = linea.strip()
        # La cabecera de proyecto va entre corchetes; el resto son etiquetas sueltas.
        if cruda.startswith("[Project:") and cruda.endswith("]"):
            campos["project"] = cruda[len("[Project:") : -1].strip()
            continue
        etiqueta, sep, valor = cruda.partition(":")
        if sep and etiqueta in ("Component", "Description", "Tech stack"):
            campos[etiqueta] = valor.strip()
    return campos


def _tarea(content: str, metadata: dict, horas: float | None) -> ReferenceTask:
    campos = _campos_del_texto(content)
    return ReferenceTask(
        component_id=str(metadata.get("component_id") or ""),
        name=campos.get("Component", ""),
        description=campos.get("Description", ""),
        tech_stack=campos.get("Tech stack", ""),
        complexity=str(metadata.get("complexity") or ""),
        estimated_hours=float(horas or 0.0),
    )


async def resolve(session: AsyncSession, reference_budget_ids: list[str]) -> dict[str, Reference]:
    """Resuelve varias referencias de una vez, indexadas por su identificador.

    En lote y no de una en una porque así es como se piden: un componente se
    respalda con cinco referencias, y abrir su detalle no debería costar cinco
    viajes. Una referencia que no exista simplemente no sale en el diccionario;
    decidir si eso es un 404 o un hueco es cosa de quien llama.
    """
    pares = {par for par in (split_reference(ref) for ref in reference_budget_ids) if par}
    if not pares:
        return {}

    stmt = (
        select(
            _BUDGET_ID,
            _MODULE,
            BudgetChunkRow.content,
            BudgetChunkRow.metadata_,
            cast(BudgetChunkRow.metadata_["estimated_hours"].astext, Float),
        )
        .where(BudgetChunkRow.chunk_type == CHUNK_TYPE)
        .where(or_(*(and_(_BUDGET_ID == b, _MODULE == m) for b, m in pares)))
        # Por id, que es el orden en el que se ingirió el presupuesto: el desglose
        # sale como estaba escrito en el original y no en un orden arbitrario.
        .order_by(BudgetChunkRow.id)
    )
    filas = (await session.execute(stmt)).all()

    agrupadas: dict[tuple[str, str], list] = {}
    for fila in filas:
        agrupadas.setdefault((fila[0], fila[1]), []).append(fila)

    referencias: dict[str, Reference] = {}
    for (budget_id, module), grupo in agrupadas.items():
        tareas = tuple(_tarea(f[2], f[3] or {}, f[4]) for f in grupo)
        primera = grupo[0]
        metadata = primera[3] or {}
        referencias[f"{budget_id}/{module}"] = Reference(
            reference_budget_id=f"{budget_id}/{module}",
            budget_id=budget_id,
            module=module,
            project=_campos_del_texto(primera[2]).get("project", ""),
            client_sector=str(metadata.get("client_sector") or ""),
            year=int(metadata["year"]) if metadata.get("year") is not None else None,
            main_technology=str(metadata.get("main_technology") or ""),
            # Sumadas aquí y no pedidas a Postgres: las tareas ya están en memoria,
            # y así el total que se enseña es literalmente el de las filas que se
            # enseñan debajo. Una suma en SQL podría cuadrar con otra cosa.
            total_hours=sum(t.estimated_hours for t in tareas),
            tasks=tareas,
        )
    return referencias
