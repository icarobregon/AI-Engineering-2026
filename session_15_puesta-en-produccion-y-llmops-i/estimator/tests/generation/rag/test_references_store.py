"""El desglose de una referencia histórica.

Lo que de verdad hay que fijar aquí es la costura: el nombre, la descripción y el
stack de una tarea sólo viven dentro del TEXTO del chunk, así que resolver una
referencia pasa por parsear lo que escribió ``render_component_text``. Dos
funciones en ficheros distintos que tienen que seguir estando de acuerdo, y nada
en el lenguaje lo obliga.

Por eso los tests no comparan contra un texto copiado a mano: llaman al
renderizador de verdad y parsean su salida. Si alguien cambia el formato, esto se
pone rojo en lugar de dejar el Drawer con las tres columnas en blanco.
"""

from __future__ import annotations

from app.generation.rag.chunking.structural import render_component_text
from app.generation.rag.schemas import Budget, BudgetComponent, ClientMetadata
from app.generation.rag.store.references import _campos_del_texto, split_reference


def _budget(*components: BudgetComponent) -> Budget:
    return Budget(
        budget_id="TASK-2022-0032",
        client_metadata=ClientMetadata(name="Acme", sector="finance", country="ES"),
        project_summary="Finance platform covering payments & billing",
        main_technology="ruby_on_rails",
        year=2022,
        total_estimated_hours=sum(c.estimated_hours for c in components),
        components=list(components),
    )


def _component(**kwargs) -> BudgetComponent:
    base = {
        "component_id": "AUTH-003",
        "name": "OAuth2 / OIDC login",
        "description": "Authorization-code flow with refresh tokens.",
        "module": "Authentication & Access",
        "tech_stack": ["redis", "postgresql"],
        "estimated_hours": 36,
        "complexity": "high",
    }
    return BudgetComponent(**{**base, **kwargs})


class TestCamposDelTexto:
    def test_saca_los_tres_campos_que_la_metadata_no_guarda(self):
        component = _component()

        campos = _campos_del_texto(render_component_text(_budget(component), component))

        assert campos["Component"] == "OAuth2 / OIDC login"
        assert campos["Description"] == "Authorization-code flow with refresh tokens."
        assert campos["Tech stack"] == "redis, postgresql"
        assert campos["project"] == "Finance platform covering payments & billing"

    def test_una_descripcion_que_imita_una_etiqueta_no_la_suplanta(self):
        # El caso que rompe un parser escrito con expresiones regulares sobre el
        # bloque entero: la frase contiene literalmente «Tech stack:».
        component = _component(description="Documents the Tech stack: nothing else.")

        campos = _campos_del_texto(render_component_text(_budget(component), component))

        assert campos["Description"] == "Documents the Tech stack: nothing else."
        assert campos["Tech stack"] == "redis, postgresql"

    def test_un_componente_sin_stack_no_inventa_nada(self):
        component = _component(tech_stack=[])

        campos = _campos_del_texto(render_component_text(_budget(component), component))

        assert campos["Tech stack"] == ""

    def test_un_componente_sin_modulo_sigue_dando_sus_campos(self):
        # `render_component_text` omite la línea Module entera cuando no hay.
        component = _component(module=None)

        campos = _campos_del_texto(render_component_text(_budget(component), component))

        assert campos["Component"] == "OAuth2 / OIDC login"


class TestSplitReference:
    def test_parte_por_la_primera_barra_y_no_por_todas(self):
        # «Frontend / UX» es un módulo real del corpus, con 115 chunks. Un
        # split("/") lo partiría en tres y no encontraría la referencia.
        assert split_reference("TASK-2024-0007/Frontend / UX") == (
            "TASK-2024-0007",
            "Frontend / UX",
        )

    def test_el_caso_corriente(self):
        assert split_reference("TASK-2022-0032/Authentication & Access") == (
            "TASK-2022-0032",
            "Authentication & Access",
        )

    def test_lo_que_no_es_una_referencia_no_lo_finge(self):
        assert split_reference("TASK-2022-0032") is None
        assert split_reference("/Authentication") is None
        assert split_reference("TASK-2022-0032/") is None
        assert split_reference("") is None
