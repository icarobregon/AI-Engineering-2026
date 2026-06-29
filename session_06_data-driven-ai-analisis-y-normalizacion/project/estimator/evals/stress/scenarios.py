"""Synthetic multi-turn scenarios for CAG stress testing.

Each scenario is a list of turns. Every turn declares:
  - ``transcript``: text to send as the user message.
  - ``fact_to_remember``: a string the LLM should cite in ALL subsequent turns
    (used by MemoryDriftMetric). ``None`` means no new fact is introduced.

Three profiles:
  - ``growing``: 20 turns, each adding a new requirement to the same project.
    Tests context accumulation, cost drift and attention degradation.
  - ``pivot``: 8 turns, tech stack pivots from React+Node to Flutter+FastAPI
    at turn 5. Tests whether the metadata update propagates the change cleanly.
  - ``contradiction``: 10 turns, budget is stated as 30k at turn 3 then
    corrected to 80k at turn 8. Tests which fact survives in the sliding window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ScenarioTurn:
    transcript: str
    fact_to_remember: Optional[str]


@dataclass
class Scenario:
    name: str
    turns: list[ScenarioTurn]
    project_type: str = "web_saas"
    detail_level: str = "medium"
    output_format: str = "phases_table"


_GROWING_TURNS: list[ScenarioTurn] = [
    ScenarioTurn(
        transcript=(
            "Necesitamos desarrollar un portal de gestión de clientes para nuestra empresa "
            "de servicios financieros. Los usuarios verán su cartera, movimientos y documentos. "
            "Estimamos unos 500 usuarios iniciales con crecimiento al doble en 12 meses."
        ),
        fact_to_remember="portal de gestión de clientes",
    ),
    ScenarioTurn(
        transcript=(
            "Quiero añadir autenticación de doble factor (2FA) obligatoria para todos los "
            "usuarios y un flujo seguro de recuperación de contraseña con enlace caducable."
        ),
        fact_to_remember="autenticación de doble factor",
    ),
    ScenarioTurn(
        transcript=(
            "También necesitamos soporte multi-tenant para poder servir a diferentes empresas "
            "clientes desde la misma plataforma, con aislamiento completo de datos entre tenants."
        ),
        fact_to_remember="multi-tenant",
    ),
    ScenarioTurn(
        transcript=(
            "Es obligatorio implementar un módulo de audit log completo para cumplimiento "
            "regulatorio. Cada acción del usuario debe registrarse con timestamp, usuario y "
            "dirección IP. Los logs deben ser inmutables y conservarse 5 años."
        ),
        fact_to_remember="audit log inmutable",
    ),
    ScenarioTurn(
        transcript=(
            "Los usuarios necesitan recibir notificaciones por email y SMS cuando hay "
            "movimientos importantes en su cartera, documentos nuevos o alertas de seguridad. "
            "El sistema de notificaciones debe ser configurable por el usuario."
        ),
        fact_to_remember="notificaciones por email y SMS",
    ),
    ScenarioTurn(
        transcript=(
            "Necesitamos una API REST documentada con OpenAPI para integraciones con los "
            "sistemas internos de los clientes empresariales. Autenticación OAuth2 con "
            "refresh tokens y scopes granulares por recurso."
        ),
        fact_to_remember="API REST OAuth2",
    ),
    ScenarioTurn(
        transcript=(
            "Hay que añadir un módulo de reporting con exportación a PDF y Excel. Los gestores "
            "deben poder generar informes personalizados: por fecha, por cliente, por activo. "
            "Los informes deben estar disponibles en el portal y enviarse por email programado."
        ),
        fact_to_remember="exportación a PDF y Excel",
    ),
    ScenarioTurn(
        transcript=(
            "El cliente quiere también una app móvil nativa para iOS y Android con las "
            "funcionalidades básicas de consulta de cartera, notificaciones push y acceso "
            "biométrico. Debe sincronizarse con el portal web en tiempo real."
        ),
        fact_to_remember="app móvil iOS y Android",
    ),
    ScenarioTurn(
        transcript=(
            "Queremos incorporar un asistente de IA que ayude a los clientes a entender "
            "su cartera, responda preguntas frecuentes y haga recomendaciones básicas basadas "
            "en su perfil de riesgo. Sin asesoramiento financiero regulado."
        ),
        fact_to_remember="asistente de IA",
    ),
    ScenarioTurn(
        transcript=(
            "Necesitamos cumplimiento GDPR completo: gestor de consentimientos, derecho al "
            "olvido con borrado en cascada, exportación de datos personales en formato "
            "machine-readable y registro de actividades de tratamiento."
        ),
        fact_to_remember="cumplimiento GDPR",
    ),
    ScenarioTurn(
        transcript=(
            "El sistema debe soportar picos de hasta 10.000 usuarios concurrentes en época "
            "de declaración de impuestos. Necesitamos auto-scaling horizontal y un SLA de "
            "99,9% de disponibilidad mensual con monitorización activa."
        ),
        fact_to_remember="auto-scaling 10.000 usuarios",
    ),
    ScenarioTurn(
        transcript=(
            "Queremos añadir un chatbot de soporte 24/7 integrado en el portal para resolver "
            "dudas frecuentes sobre operativa del portal, sin intervención humana en el "
            "primer nivel. Escalada automática al soporte humano si el bot no resuelve."
        ),
        fact_to_remember="chatbot de soporte 24/7",
    ),
    ScenarioTurn(
        transcript=(
            "Necesitamos integración directa con los 3 principales bancos custodios vía API "
            "para sincronización automática de posiciones, movimientos y precios. "
            "La frecuencia de sincronización debe ser configurable por tenant."
        ),
        fact_to_remember="integración con bancos custodios",
    ),
    ScenarioTurn(
        transcript=(
            "El módulo de documentos debe soportar firma digital de documentos contractuales "
            "con validez legal en España y la UE, cumpliendo el reglamento eIDAS. "
            "Integración con al menos un proveedor de firma cualificada."
        ),
        fact_to_remember="firma digital eIDAS",
    ),
    ScenarioTurn(
        transcript=(
            "Necesitamos un dashboard ejecutivo con KPIs en tiempo real para los gestores: "
            "AUM total, captación neta del mes, número de clientes activos, distribución "
            "por perfil de riesgo y top 10 activos por volumen."
        ),
        fact_to_remember="dashboard ejecutivo KPIs",
    ),
    ScenarioTurn(
        transcript=(
            "Hay que implementar alertas configurables por el usuario: cuando el valor de "
            "la cartera baje más de X%, cuando llegue un documento a firmar, cuando se acerque "
            "el vencimiento de un plazo fijo. Las alertas llegan por email, SMS y push."
        ),
        fact_to_remember="alertas configurables",
    ),
    ScenarioTurn(
        transcript=(
            "El portal debe ser accesible según WCAG 2.1 nivel AA. Esto incluye lectores de "
            "pantalla, navegación solo con teclado, contraste mínimo y textos alternativos en "
            "todos los elementos gráficos. Auditoria externa de accesibilidad al lanzamiento."
        ),
        fact_to_remember="accesibilidad WCAG 2.1 AA",
    ),
    ScenarioTurn(
        transcript=(
            "Necesitamos un módulo de simulación de carteras donde el cliente pueda modelar "
            "escenarios hipotéticos: qué ocurre si reinvierto dividendos, si cambio el perfil "
            "de riesgo, si aporto X€ mensuales. Con proyección gráfica a 5 y 10 años."
        ),
        fact_to_remember="simulación de carteras",
    ),
    ScenarioTurn(
        transcript=(
            "Queremos añadir gamificación: badges por objetivos de ahorro conseguidos, "
            "ranking entre usuarios que hayan dado su consentimiento explícito, y recompensas "
            "en forma de reducción de comisiones. Sistema opt-in obligatorio."
        ),
        fact_to_remember="gamificación con badges",
    ),
    ScenarioTurn(
        transcript=(
            "El sistema completo debe estar desplegado en infraestructura cloud certificada "
            "ISO 27001 con disaster recovery activo en otra región europea. "
            "RTO máximo de 4 horas, RPO máximo de 1 hora. Certificación SOC 2 Tipo II en 18 meses."
        ),
        fact_to_remember="ISO 27001 SOC 2",
    ),
]

_PIVOT_TURNS: list[ScenarioTurn] = [
    ScenarioTurn(
        transcript=(
            "Vamos a construir una aplicación de gestión de tareas para equipos de desarrollo. "
            "Frontend en React con TypeScript y Tailwind, backend en Node.js con Express. "
            "Arrancamos con 20 equipos piloto, unos 200 usuarios en total."
        ),
        fact_to_remember="React TypeScript",
    ),
    ScenarioTurn(
        transcript=(
            "Necesitamos tablero kanban con drag-and-drop, gestión de sprints con backlog "
            "priorizable, burndown chart automático e integración con GitHub para vincular "
            "commits y pull requests a tareas específicas."
        ),
        fact_to_remember="kanban drag-and-drop",
    ),
    ScenarioTurn(
        transcript=(
            "Los usuarios colaborarán en tiempo real: comentarios en tareas con menciones, "
            "notificaciones push en el navegador, y actualizaciones instantáneas del tablero "
            "sin recargar la página. Usaremos WebSockets para las actualizaciones."
        ),
        fact_to_remember="WebSockets tiempo real",
    ),
    ScenarioTurn(
        transcript=(
            "Hay que añadir un módulo de reporting: velocidad del equipo por sprint, "
            "tiempo medio de resolución por tipo de tarea, comparativa entre sprints y "
            "exportación de métricas a CSV para análisis externo."
        ),
        fact_to_remember="reporting velocidad equipo",
    ),
    ScenarioTurn(
        transcript=(
            "CAMBIO DE PLANTEAMIENTO TÉCNICO: El cliente ha revisado su estrategia móvil y "
            "ha decidido que abandonamos React web y Node.js. La aplicación se construirá "
            "como app Flutter multiplataforma (iOS, Android y web desde un único codebase). "
            "El backend pasa a ser Python con FastAPI. React y Node.js quedan fuera del scope."
        ),
        fact_to_remember="Flutter FastAPI",
    ),
    ScenarioTurn(
        transcript=(
            "Siguiendo con la arquitectura Flutter+FastAPI: necesitamos sincronización "
            "offline completa. Los desarrolladores deben poder crear y editar tareas sin "
            "conexión, y que todo se sincronice automáticamente al reconectarse. "
            "Estrategia optimistic updates con resolución de conflictos."
        ),
        fact_to_remember="sincronización offline Flutter",
    ),
    ScenarioTurn(
        transcript=(
            "La app Flutter debe tener tema oscuro y claro adaptativos según la preferencia "
            "del sistema operativo, una UI diseñada específicamente para mobile-first con "
            "gestos nativos, y widgets propios de la marca sin depender de Material 3."
        ),
        fact_to_remember="tema oscuro Flutter",
    ),
    ScenarioTurn(
        transcript=(
            "Para el lanzamiento internacional necesitamos soporte completo en español e inglés, "
            "con arquitectura de internacionalización (i18n) que permita añadir nuevos idiomas "
            "sin cambios en el código. Pluralización y formato de fechas por locale."
        ),
        fact_to_remember="internacionalización i18n",
    ),
]

_CONTRADICTION_TURNS: list[ScenarioTurn] = [
    ScenarioTurn(
        transcript=(
            "Necesitamos un sistema de gestión de inventario para una cadena de tiendas de "
            "moda con 50 locales en España. Los encargados controlarán stock, recepciones y "
            "transferencias entre tiendas. Tiempo estimado de proyecto: 6 meses."
        ),
        fact_to_remember="gestión de inventario 50 tiendas",
    ),
    ScenarioTurn(
        transcript=(
            "El sistema debe integrarse con el ERP SAP Business One existente para sincronizar "
            "productos y precios, gestionar el stock en tiempo real y sincronizarse con la "
            "tienda online WooCommerce para evitar sobreventas."
        ),
        fact_to_remember="integración SAP WooCommerce",
    ),
    ScenarioTurn(
        transcript=(
            "Importante antes de seguir: el presupuesto máximo aprobado por el comité de "
            "dirección es de 30.000 euros. Es un límite fijo, no negociable. "
            "Todo el scope debe caber dentro de ese presupuesto."
        ),
        fact_to_remember="presupuesto 30.000 euros",
    ),
    ScenarioTurn(
        transcript=(
            "Quiero añadir también un módulo de predicción de demanda con machine learning "
            "para optimizar los pedidos a proveedores y reducir el stock muerto en tienda. "
            "Debería aprender de las ventas históricas y la estacionalidad."
        ),
        fact_to_remember="predicción de demanda ML",
    ),
    ScenarioTurn(
        transcript=(
            "El sistema debe funcionar sin conexión a internet en las tiendas durante los "
            "cortes habituales de conectividad, sincronizando automáticamente cuando se "
            "restaure la conexión. Modo offline completo para recepciones y ventas."
        ),
        fact_to_remember="modo offline tienda",
    ),
    ScenarioTurn(
        transcript=(
            "Los responsables de zona necesitan un dashboard con métricas de cada tienda: "
            "rotación de stock por categoría, mermas, ventas diarias vs objetivo, "
            "y ranking de tiendas por eficiencia de inventario."
        ),
        fact_to_remember="dashboard por zona",
    ),
    ScenarioTurn(
        transcript=(
            "Necesitamos integración con los terminales de punto de venta (TPV) ya instalados "
            "en tiendas, que son de tres fabricantes distintos: Ingenico, Verifone y PAX. "
            "La integración debe actualizar el stock automáticamente con cada venta."
        ),
        fact_to_remember="integración TPV tres fabricantes",
    ),
    ScenarioTurn(
        transcript=(
            "Buenas noticias: la empresa ha obtenido financiación adicional de un fondo de "
            "inversión. El presupuesto del proyecto queda ampliado a 80.000 euros. "
            "Con este presupuesto el cliente quiere desarrollar todo lo discutido y además "
            "añadir funcionalidades adicionales sin restricciones de coste previas."
        ),
        fact_to_remember="presupuesto ampliado 80.000 euros",
    ),
    ScenarioTurn(
        transcript=(
            "Con el presupuesto ampliado, queremos añadir una app móvil para los encargados "
            "de tienda con inventario rápido mediante escáner de código de barras y QR, "
            "y pedidos a proveedor directamente desde el móvil sin acceder al ordenador."
        ),
        fact_to_remember="app móvil encargados escáner",
    ),
    ScenarioTurn(
        transcript=(
            "Confirmamos que el scope final incluye todo lo discutido en esta sesión. "
            "¿Cuál sería la estimación completa del proyecto con todos los módulos, "
            "incluyendo integración SAP, WooCommerce, TPV, predicción de demanda, "
            "modo offline, dashboard y app móvil?"
        ),
        fact_to_remember=None,
    ),
]


SCENARIOS: dict[str, Scenario] = {
    "growing": Scenario(name="growing", turns=_GROWING_TURNS),
    "pivot": Scenario(name="pivot", turns=_PIVOT_TURNS),
    "contradiction": Scenario(name="contradiction", turns=_CONTRADICTION_TURNS),
}
