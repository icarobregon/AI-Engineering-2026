# Sesión 5 — Funcionalidades avanzadas

## Objetivo de la sesión

En la sesión anterior diste un salto importante: pasaste de construir interfaces basadas en chat a diseñar sistemas donde tú controlas el comportamiento. Definiste estructuras, separaste responsabilidades y empezaste a tratar los prompts como parte del código. Tu sistema dejó de depender del usuario y empezó a comportarse como un producto.

Pero todavía hay algo que no está resuelto. Aunque ahora tienes más control, tu sistema sigue siendo esencialmente estático: responde bien dentro de un contexto limitado, en una única interacción, y bajo condiciones bastante controladas.

El problema es que eso no es lo que ocurre en producción. Los usuarios no hacen una única petición. El contexto no está cerrado. La información relevante no vive solo en el prompt. Y, sobre todo, la calidad deja de ser evidente.

En esta sesión cerramos el módulo de arquitectura CAG con cuatro piezas que casi nadie enseña a la vez: cómo enriquecer el contexto con información del mundo real, cómo gestionar la memoria sin que se descontrole, cómo adaptar la salida a cada perfil de usuario y cómo evaluar la calidad cuando el output ya no se puede comparar con un valor esperado. A estas cuatro piezas se suma el patrón Actor-Critic-Boss, que rompe el techo de calidad de cualquier sistema de generación.

→ Por qué un sistema sin contexto dinámico, memoria explícita ni adaptación por perfil se queda en demo, y cómo se aborda cada uno con código que cabe en un servicio FastAPI.

→ Cuál es la disciplina mínima de testing y evaluación que separa un equipo que itera con confianza de uno que tiene miedo a tocar los prompts.

→ Cómo el patrón Actor-Critic-Boss compone tres roles diferenciados para producir respuestas significativamente más sólidas, sin frameworks adicionales y con anclaje sólido en la literatura.

## Qué vas a aprender

### 1. 📄 Integración de contexto dinámico desde fuentes externas

Hasta la sesión 04, todo el contexto que ha viajado al LLM ha sido estático: vive en código o en parámetros tipados que el formulario produce. El contexto dinámico es el que el sistema obtiene en tiempo de ejecución, en respuesta a una petición concreta. Este artículo cubre los tres mecanismos canónicos para enriquecer el contexto de un sistema CAG en tiempo de ejecución sin saltar todavía a una arquitectura RAG.

**La distinción crítica: contexto estático vs contexto dinámico**

Tres reglas operativas antes de implementar cualquier mecanismo:

- Regla 1 — el contexto dinámico es input, no programa. Cualquier contenido que entra desde fuera del sistema debe estar claramente delimitado en el prompt y nunca se le da al LLM la capacidad de interpretarlo como instrucciones (prompt injection).
- Regla 2 — el contexto dinámico tiene coste real por petición. Mientras el contexto estático se paga una vez en token caching, el dinámico se reincluye en cada llamada y consume tokens nuevos.
- Regla 3 — el contexto dinámico introduce latencia que el usuario nota. Procesar un PDF puede llevar 1–3 segundos; una búsqueda web añade 2–5 segundos más.

**Mecanismo 1 — Archivos adjuntos**

Hay dos caminos canónicos para incorporar documentos al contexto:

_Camino A — Multimodal directo_: el PDF viaja al LLM usando la Files API de OpenAI o Anthropic. El modelo extrae texto, interpreta diagramas y razona sobre el contenido visual. Más simple, menos código, pero acoplado al proveedor multimodal. Los archivos se suben una vez y se referencian por `file_id` en los turnos siguientes.

_Camino B — Extracción local_: se extrae el contenido del documento en el servicio IA antes de la llamada al LLM y se envía solo texto. Para PDFs nativos de texto: `pypdf` o `PyMuPDF`. Para PDFs escaneados o con layout complejo: `Docling` o `MarkItDown`. Para Word: `python-docx`. El contenido se concatena al prompt con delimitadores XML claros (`<attachment filename='...'>`). Más control, independiente del proveedor, y prepara el terreno para el chunking de RAG en el módulo 3.

**Mecanismo 2 — Búsqueda web**

Tres aproximaciones con distintos niveles de control y acoplamiento:

- _Herramienta nativa del proveedor_: OpenAI y Anthropic exponen búsqueda web como herramienta de primera clase (`tools=[{"type": "web_search"}]`). Más simple, mejor integrada con el razonamiento del modelo, pero lock-in total.
- _Servicio de búsqueda independiente_: Tavily, Exa o Firecrawl devuelven resultados optimizados para consumo por modelos. Se expone como function calling. Independiente del proveedor.
- _SERP API tradicional_: SerpAPI o Serper devuelven resultados estructurados de Google. Máximo control, máxima carga de mantenimiento.

La regla práctica: activar búsqueda web solo para tecnologías recientes, comparativas de precios de SaaS, benchmarks recientes o disponibilidad de librerías. Para el resto, el modelo ya tiene la información en su corte de entrenamiento.

**Mecanismo 3 — Consultas a la BBDD del backend de negocio**

El patrón correcto es expresar la consulta como herramienta (function calling) que el LLM puede invocar, donde la implementación hace una llamada HTTP al backend de negocio. El servicio IA nunca accede directamente a la BBDD del backend: preserva las tres capas del programa.

```
LLM → Servicio IA (Python) → Backend de negocio (Rails) → PostgreSQL
       (define la tool)      (HTTP autenticada)           (aplica reglas de negocio)
```

El patrón es independiente del stack del backend (Rails, NestJS, Spring, Django, Go). Se comunican por contrato HTTP, nunca por BBDD compartida.

**Combinando los tres mecanismos**

En un caso real pueden coexistir en la misma petición. El patrón general que los orquesta es el agentic loop: el LLM razona, decide qué herramienta invocar, recibe los resultados, razona de nuevo, y produce la respuesta final. Dos disciplinas imprescindibles: budget de tokens por turno y trazabilidad (cada herramienta invocada es un nuevo span observable).

### 2. 📄 Memoria conversacional vs historial: estrategias para sistemas CAG

**Definiciones operativas**

- **Historial conversacional**: el array de mensajes (system, user, assistant…) que viaja a la API del LLM en cada llamada. Estructura bruta en orden cronológico.
- **Memoria conversacional**: el conjunto de hechos relevantes destilados sobre el dominio de la conversación. Los hechos no son turnos; son afirmaciones destiladas. Persiste aunque el turno original haya caído fuera de la ventana deslizante.

Tres razones operativas para mantenerlas como estructuras independientes: coste y latencia (la memoria es compacta y no crece linealmente), resistencia al truncado (sobrevive a la ventana deslizante), y auditabilidad (los hechos asumidos son inspeccionables).

**Anatomía del estado conversacional**

Una sesión del estimator tiene tres componentes de estado:

```python
class ProjectMetadata(BaseModel):
    """Distilled facts about the project. Survives history truncation."""
    project_name: str | None = None
    assumed_team_size: int | None = None
    mentioned_technologies: list[str] = Field(default_factory=list)
    agreed_scope: str | None = None
    explicit_constraints: list[str] = Field(default_factory=list)
    rejected_options: list[str] = Field(default_factory=list)

class Session(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    history: list[Message] = Field(default_factory=list)
    project_metadata: ProjectMetadata = Field(default_factory=ProjectMetadata)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

**Inyección de memoria en el system prompt**

El template Jinja2 recibe un bloque `<project_metadata>` con los hechos conocidos, con renderizado condicional por campo. La instrucción clave al final del system prompt: "treat the project_metadata as established facts". Sin esa instrucción, el LLM tiende a tratar la memoria como sugerencia y renegociar hechos ya cerrados.

**Actualizar la memoria tras cada turno**

Dos aproximaciones canónicas:

- _Heurística simple_: reglas explícitas (regex, vocabulario de tecnologías) que extraen hechos del turno. Coste cero, latencia despreciable, comportamiento predecible. Frágil ante variaciones de lenguaje.
- _LLM extractor_: segunda llamada al LLM con prompt específico que devuelve JSON con los campos del `ProjectMetadata` actualizado. Robusto, multilingüe, captura hechos sutiles. Coste extra por turno (~céntimos con modelos ligeros) y riesgo de extracción errónea que se propaga a todos los turnos siguientes.

Criterio de elección: dominio acotado y lenguaje predecible → heurística. Dominio abierto, multilingüe o variabilidad alta → LLM extractor.

**Estrategias de gestión del historial**

Con `project_metadata` separado, la ventana deslizante simple deja de ser arriesgada porque los hechos que importan no se pierden cuando un turno cae de la ventana. `MAX_TURNS = 6` con `project_metadata` actualizado por turno es una arquitectura completamente razonable para producción inicial.

**Políticas de olvido**

- Revisión explícita por el usuario (lógica de actualización de memoria)
- TTL por sesión (sesión inactiva 24h → archivada)
- Reset explícito (endpoint `POST /sessions` crea sesión nueva)

**Anti-patrones frecuentes**

- Memoria en el system prompt como string libre (no tipado, imposible de mantener a partir del turno 20)
- Confiar en que el LLM "se acordará" entre llamadas (no tiene estado entre llamadas)
- Mezclar memoria e historial en una única estructura (la factura llega cuando necesitas truncar el historial sin tocar la memoria)

### 3. 📄 Prompts adaptativos por perfil de usuario: el patrón "tier"

Un sistema con un único system prompt entrega la misma respuesta a todos los usuarios. Un desarrollador senior necesita desglose por componentes técnicos con horas y riesgos; un director comercial necesita coste agregado, duración y nivel de confianza global. Con prompt único, ninguno queda bien servido — y los usuarios empiezan a acompañar la transcripción con instrucciones, volviendo al patrón de chat que se combatió en la sesión 04.

**La decisión arquitectónica: tier como dimensión del producto**

El patrón se implementa en tres capas independientes:

_Capa 1 — Persistencia_: columna `tier` en la tabla `users` del backend de negocio con valores enumerados (`developer`, `pm`, `executive`). El tier es una dimensión de producto (qué experiencia recibe el usuario), no un rol de autorización (qué puede hacer).

_Capa 2 — Propagación_: el backend de negocio propaga el tier al servicio IA por un canal que el cliente final no puede manipular: claim en JWT firmado, o header en red privada (VPC). Nunca como parámetro libre desde el cliente.

_Capa 3 — Materialización_: el servicio IA usa el tier para seleccionar el template Jinja2 y el schema Pydantic de salida.

```python
TIER_CONFIG = {
    "developer": {"template": "estimate_developer.j2", "schema": DeveloperEstimate},
    "pm":        {"template": "estimate_pm.j2",        "schema": PmEstimate},
    "executive": {"template": "estimate_executive.j2", "schema": ExecutiveEstimate},
}
```

**Diseñando los templates por tier**

Los tres templates comparten bloques comunes vía `{% include %}` (project_metadata, reference_estimates) y se diferencian en instrucciones específicas y schema de salida. El schema actúa como segundo guardrail: si el LLM olvida una sección, la validación falla antes de que el usuario reciba algo defectuoso.

La regla operativa: adaptar a un perfil significa adaptar la estructura de salida, no solo el tono. Schemas Pydantic distintos por tier es la prueba de que el patrón está bien implementado. Un tier que solo cambia el tono con un `{% if tier == "executive" %}` en un único template es lock-in cosmético, no diseño de producto.

**Evolución del patrón**

El patrón escala desde "misma pipeline, distinto template" hasta "pipeline completamente distinta". Un tier `research` puede activar un modelo distinto (`o3-deep-research`), búsqueda web por defecto, modo background con utos, y entrega por email. Conocer ese rango de aplicación cambia cómo se diseña la abstracción desde el primer día.

**Anti-patrones frecuentes**

- El tier vive en el frontend (cualquier usuario puede manipular el parámetro)
- Un solo schema con branching de campos (el contrato deja de ser nítido)
- Los templates por tier divergen sin disciplina (parciales con `{% include %}` son obligatorios)

### 4. 📄 Testing y evaluación de sistemas con LLMs

El test unitario clásico (`assert result.total_hours == 16`) falla el 30% de las veces aunque el sistema funcione perfectamente. En sistemas con LLM el test no comprueba igualdad sino propiedades. Para el estimator: output válido contra el schema Pydantic, horas en rango razonable, componentes coherentes con la transcripción, sin contradicción con `project_metadata`, consistencia entre invocaciones repetidas.

**Tres familias de tests**

_Familia 1 — Tests deterministas hard_: verificación estructural o numérica que no involucra el LLM. El output es JSON válido contra el schema, campos obligatorios presentes, horas dentro de límites razonables, número de componentes entre mínimo y máximo. Determinísticos, baratos, rápidos. Primera capa obligatoria.

_Familia 2 — Tests deterministas soft_: propiedades estadísticas. El test ejecuta el sistema N veces sobre el mismo input y verifica que la distribución de respuestas tiene la forma esperada. Coeficiente de variación del rango de horas por debajo del 25%. Detectan problemas de consistencia que ningún test hard puede capturar. Más caros (N llamadas al LLM). Correr en CI antes de merge a main, no en cada commit.

_Familia 3 — Tests de calidad subjetiva (LLM-as-judge)_: propiedades genuinamente subjetivas que solo un juez puede valorar. El patrón canónico usa DeepEval con `GEval`: una segunda llamada al LLM con criterios explícitos emite un veredicto (score 0–1). Más costosa y más lenta. Reservar para propiedades que no se pueden capturar de otra forma. El umbral (threshold) no es universal: calibrar con casos donde un humano ha emitido el veredicto.

**El golden dataset**

Un conjunto curado de 5–15 transcripciones representativas del dominio, cada una anotada con comportamiento esperado: categoría, rango de horas de referencia, riesgos clave, componentes que deberían aparecer. No es una lista de inputs; es una lista de inputs con criterios de éxito. Construirlo es inversión, no coste: detectar antes de producción que un cambio de prompt rompe casos medios paga el dataset varias veces. Revisión recomendada cada trimestre.

**Suite de evals con DeepEval y pytest**

```python
# Separar tests costosos con marcador
@pytest.mark.slow
@pytest.mark.parametrize("golden", golden_dataset.goldens)
def test_scope_coherence(golden):
    result = estimate_sync(tier="developer", transcript=golden.input)
    test_case = LLMTestCase(input=golden.input, actual_output=result.model_dump_json())
    assert_test(test_case, [coherence_metric])
```

La suite es piramidal: muchos tests hard rápidos en la base, algunos tests soft en el medio, pocos tests subjetivos en la cima. Ejecutar `pytest -m "not slow"` en local y la suite completa en CI antes de merge.

**Anti-patrones frecuentes**

- Testar la respuesta del modelo en lugar de propiedades del sistema (cuando OpenAI actualiza el modelo, todos los tests rompen aunque no haya bug)
- Suite de evals que es solo familia 3 (lentísima, carísima, mismo punto de fallo)
- Construir el golden dataset una vez y olvidarlo (tests verdes y producción fallando en 6 meses)

### 5. 📄 Actor-Critic-Boss: la composición de roles que eleva la calidad

Hay un techo de calidad que no se rompe solo refinando prompts. Una estimación generada en una sola pasada es buena en promedio, pero inconsistente en los casos donde el coste del error es más alto: aritméticas internas que no cuadran, riesgos que no se mencionan, componentes que aparecen en la justificación pero no en el desglose de horas. El problema no es de instrucción sino de verificación.

Madaan et al. mostraron en Self-Refine (2023) que separar generación de feedback en dos llamadas mejora la calidad del output un 20% absoluto en promedio sobre siete tareas, sin entrenamiento adicional.

**Los tres roles**

- **Actor**: genera la estimación inicial a partir de la transcripción, adjuntos y `project_metadata`. Es la llamada al LLM que el estimator ya hace hoy. Su salida deja de ser la respuesta final y pasa a ser un candidato.
- **Critic**: recibe el output del actor y lo evalúa contra criterios explícitos: ¿está completo?, ¿la aritmética cuadra?, ¿los riesgos son coherentes con el alcance?, ¿hay contradicciones con el `project_metadata`?, ¿faltan componentes que la transcripción menciona? Produce feedback estructurado (lista de issues con categoría, severidad y referencia al campo afectado), no texto libre.
- **Boss**: recibe la estimación del actor + el feedback del critic. Decide: aceptar si no hay problemas materiales, devolver al actor con instrucciones específicas para nueva iteración, o sintetizar la versión final integrando correcciones. Opera siempre con un presupuesto máximo de iteraciones (típicamente 2–3). Cuando se agota, entrega la mejor respuesta disponible aunque no sea perfecta.

**Por qué tres roles y no dos**

Separar evaluación de decisión rompe dos modos de fallo del Self-Refine puro: bucles infinitos por insatisfacción crónica (el critic siempre encuentra algo que mejorar sin árbitro externo) y sesgo de confirmación temprana (el critic se convierte en cómplice del actor, especialmente cuando es el mismo LLM). El paralelo humano: el ingeniero hace el trabajo, el revisor identifica problemas, y el tech lead decide qué es bloqueante para el merge.

**Anclaje en la literatura**

| Rol    | Equivalente en la literatura | Fuente                                                                             |
| ------ | ---------------------------- | ---------------------------------------------------------------------------------- |
| Actor  | Generator / Optimizer        | Anthropic, _Building Effective Agents_ (2024); Madaan et al., _Self-Refine_ (2023) |
| Critic | Evaluator / Self-Verifier    | Anthropic, _Building Effective Agents_; Shinn et al., _Reflexion_ (2023)           |
| Boss   | Orchestrator / Supervisor    | Anthropic, _Building Effective Agents_ (orchestrator-workers workflow)             |

**Cuándo el patrón compensa y cuándo es overkill**

Compensa cuando se cumplen al menos dos de estas condiciones: el coste del error es alto (contrato comercial basado en la estimación), existen criterios de evaluación claros, y la latencia adicional es tolerable. Es overkill para tareas simples, cuando hay tests deterministas hard que ya cubren los modos de fallo importantes, o cuando los criterios de evaluación son demasiado vagos. Aplicarlo solo a los caminos críticos del producto, no a todas las llamadas al LLM.

**Anti-patrones frecuentes**

- Tres llamadas con prácticamente el mismo prompt (tres veces el coste sin ganancia de calidad)
- El critic devuelve texto libre en lugar de feedback estructurado con schema Pydantic
- Iteraciones sin límite explícito de rondas

## Ejercicios prácticos

### ✍️ Ejercicio — Memoria conversacional y contexto enriquecido

**Contexto del ejercicio**

Hasta la sesión 04 el estimator ha sido un sistema transaccional: una transcripción entra, una estimación sale. El objetivo de este ejercicio es añadir dos capacidades concretas antes del directo: memoria conversacional dentro de una sesión (el contexto del proyecto en curso se preserva entre turnos sin reenviar todo el historial bruto) y soporte de adjuntos (PDFs y documentos Word que enriquecen la transcripción con especificaciones técnicas, propuestas previas o diagramas de arquitectura).

**Punto de partida**

Al final de la sesión 04 se tiene:

- Servicio IA en FastAPI con wrapper de proveedores que abstrae OpenAI y Anthropic, caching, streaming y observabilidad básica con structlog.
- Endpoint principal del estimator que recibe parámetros tipados y una transcripción, y devuelve una estimación estructurada validada por schema Pydantic.
- Templates Jinja2 versionados para los prompts.
- Guardrails programáticos sobre la salida.
- Cliente Streamlit con formulario que produce los parámetros tipados.

**Objetivos de aprendizaje**

Al terminar el ejercicio se debe poder defender en conversación técnica: la diferencia operativa entre historial y memoria, por qué la ventana deslizante es la estrategia por defecto razonable, cómo separar la gestión del historial conversacional de la gestión de los hechos del proyecto (`project_metadata`), las dos formas canónicas de procesar adjuntos (multimodal vs extracción local) y cuándo elegir cada una, y cómo gestionar `multipart/form-data` con FastAPI cuando hay parámetros tipados y archivos en la misma petición.

**Lo que entra en el ejercicio**

_Paso 1 — Modelar el estado de la sesión_: crear `sessions.py` en el servicio IA con `ConversationHistory` (lista limitada de mensajes con lógica de ventana deslizante, preservando siempre el system prompt) y `ProjectMetadata` (Pydantic model con `project_name`, `assumed_team_size`, `mentioned_technologies`, `agreed_scope`). Ambas estructuras viven dentro de una clase `Session` indexada por `session_id` en un diccionario en memoria del proceso.

_Paso 2 — Endpoint para crear sesiones_: `POST /sessions` que devuelve `{"session_id": "..."}` (UUID v4). El `session_id` viaja en cada petición posterior.

_Paso 3 — Soporte de adjuntos en el endpoint principal_: endpoint `POST /sessions/{session_id}/estimate` aceptando `multipart/form-data` con `transcript` (string) y `attachments` (lista opcional de `UploadFile`). Elegir uno de los dos caminos:

- **Camino A (multimodal directo)**: subir el PDF a la Files API de OpenAI o Anthropic y referenciarlo en el bloque de contenido del mensaje con su `file_id`.
- **Camino B (extracción local)**: extraer texto localmente con `pypdf`/`PyMuPDF` para PDFs y `python-docx` para Word, concatenar al transcript con separador `--- attachment: filename.pdf ---`.

_Paso 4 — Inyección de `project_metadata` en el system prompt_: modificar el template Jinja2 del system prompt para recibir un bloque `<project_metadata>`. Actualizar la metadata después de cada respuesta del LLM usando heurística simple (regex + vocabulario de tecnologías) o LLM extractor (segunda llamada con prompt específico que devuelve JSON). Justificar la decisión en el README.

_Paso 5 — Gestión del historial con ventana deslizante_: `MAX_TURNS = 6` como valor por defecto (ajustable por configuración). Un turno es un par user+assistant. El system prompt se preserva como invariante. Exponer método `to_messages_list()` que devuelva el array `messages` listo para la API, con el system prompt regenerado desde el `project_metadata` actual.

_Paso 6 — Adaptar el cliente_: crear sesión al cargar la página y guardar el `session_id` en `session_state`. Añadir campo de texto para transcripción y selector múltiple de archivos. Mostrar el `project_metadata` actual en panel lateral (útil para debugging). Botón "Nueva conversación" que llame a `POST /sessions` y resetee el estado.

_Paso 7 — Tests mínimos_: con `pytest` y `httpx.AsyncClient`:

- Una sesión que enlaza dos peticiones y verifica que el `project_metadata` se actualiza correctamente.
- Una petición con PDF adjunto que verifica que el contenido del documento influye en la estimación.
- Un test que envía 8 turnos a la misma sesión y verifica que el historial efectivo enviado al LLM nunca supera `MAX_TURNS`.

**Lo que no entra en el ejercicio** (se construye en el directo)

- Estrategia de resumen acumulativo o híbrida con anclas.
- Tier dinámico derivado de contexto en runtime.
- Persistencia de la memoria entre reinicios del servicio.
- Búsqueda web integrada y function calling para BBDD del backend de negocio.
- Patrón Actor-Critic-Boss.

**Criterios de "hecho"**

- `POST /sessions` crea una sesión y devuelve un `session_id`.
- `POST /sessions/{session_id}/estimate` acepta `multipart/form-data` con transcripción y adjuntos opcionales, y devuelve una estimación que respeta el schema Pydantic existente.
- Tras varios turnos en la misma sesión, el LLM responde con coherencia respecto al proyecto en curso.
- El `project_metadata` se actualiza visiblemente entre turnos.
- El historial respeta el límite de la ventana deslizante.
- README breve indicando qué camino de adjuntos se eligió y por qué, y cómo se extrae el `project_metadata`.
- Los tests del Paso 7 pasan en local.

**Entregable**

Una rama `pre-session-05` en el repositorio con todos los cambios. README breve actualizando cómo se levanta, cómo se ejecutan los tests, qué camino de adjuntos se eligió y cómo se extrae el `project_metadata`. Captura o GIF de la nueva interfaz mostrando una conversación de al menos tres turnos con el panel de `project_metadata` visible (opcional, pero ayuda en la review en directo).

Plazo de entrega: enviar el enlace a la rama a Lia por WhatsApp o a george@lidr.co con al menos dos días de antelación a la sesión en vivo.

**Nota sobre tiers y complejidad**: el patrón tier tiene sentido cuando existen distintos tipos de usuarios que necesitan respuestas diferentes. No es un patrón necesario en todos los proyectos — en la mayoría de casos iniciales añadirlo introduce complejidad innecesaria. En este ejercicio el objetivo es explorar el concepto, no implementarlo de forma completa. Un tier no es lo mismo que autenticación ni permisos, ni es equivalente a un simple `if` dentro del prompt.

---

## Decisiones de implementación

### Adjuntos — Camino B (extracción local)

Se eligió **Camino B** sobre el Camino A (multimodal Files API) por tres razones:

1. **Sin lock-in de proveedor**: funciona con cualquier modelo via LiteLLM, no sólo Anthropic.
2. **Control fino**: se decide exactamente qué texto entra al contexto; útil para filtrar cabeceras irrelevantes de un PDF antes de enviarlo al LLM.
3. **Preparación para RAG**: el texto extraído localmente es el mismo que el pipeline de chunking de las sesiones 7+ necesita. El Camino A no prepara ese pipeline.

Formatos soportados: **PDF** (`pypdf`) y **DOCX** (`python-docx`). Otros formatos se aceptan pero se omiten con un warning sin abortar la petición.

El texto extraído se concatena al transcript con el separador:

```
--- attachment: <filename> ---
```

Los guardrails de entrada corren sobre el **texto combinado** (transcript + adjuntos). Limitación conocida: PII en un adjunto bloquea la petición con HTTP 400.

### Extracción de ProjectMetadata — LLM extractor

Se eligió el **LLM extractor** sobre la heurística regex por:

- Las transcripciones son texto libre en ES/EN con alta variabilidad → regex sería frágil.
- El modelo recibe `response_model=ProjectMetadata` (Instructor + Pydantic), lo que garantiza un JSON bien formado incluso si el modelo es impreciso.
- El coste es una segunda llamada LLM ligera (~512 tokens, modelo primario) por turno.

La regla del README lo confirma: _"dominio abierto, multilingüe, con variabilidad alta → LLM extractor"_.

La fusión de metadata sigue la política:

- **Escalares** (`project_name`, `assumed_team_size`, `agreed_scope`): sobrescriben el valor previo sólo cuando el extractor devuelve un valor no nulo.
- **Listas** (`mentioned_technologies`, `explicit_constraints`, `rejected_options`): se acumulan (unión sin duplicados, insensible a mayúsculas).

---

## Arquitectura añadida en la sesión 5

```
POST /sessions                    → crea sesión (uuid4), devuelve session_id
POST /sessions/{id}/estimate      → turno conversacional (multipart/form-data)
  └── attachments.py              → extracción local PDF/DOCX
  └── services/conversation.py   → orquestador del turno
      ├── check_input()           → guardrails de entrada (heredado)
      ├── render_estimation_prompt_with_metadata()  → prompt v2 con <project_metadata>
      ├── llm_wrapper.complete_structured(..., history=...)  → estimación
      ├── enforce_scope_response()                 → guardrail de salida (heredado)
      └── _extract_and_merge_metadata()            → LLM extractor + merge
  └── sessions.py                 → ConversationHistory + ProjectMetadata + SessionStore
```

Los endpoints transaccionales (`/api/v1/estimate`) y la caché Redis no se modificaron.

---

## Checklist antes de la siguiente sesión

- [ ] Entiendes la diferencia operativa entre historial (el array `messages` que viaja a la API) y memoria (los hechos destilados sobre el proyecto en curso)
- [ ] Sabes por qué la memoria necesita ser una estructura independiente del historial y cuáles son las tres razones operativas (coste, resistencia al truncado, auditabilidad)
- [ ] Puedes defender cuándo elegir el Camino A (multimodal directo) y el Camino B (extracción local) para procesar adjuntos
- [ ] Entiendes las dos formas de actualizar `project_metadata` (heurística vs LLM extractor) y los criterios para elegir
- [ ] Sabes implementar `multipart/form-data` con FastAPI con parámetros tipados y archivos en la misma petición
- [ ] Entiendes el patrón tier como dimensión de producto (no de autorización) y sus tres capas: persistencia en BBDD, propagación por JWT/header, materialización en template+schema
- [ ] Sabes que adaptar a un perfil significa adaptar la estructura de salida, no solo el tono
- [ ] Conoces las tres familias de tests para sistemas con LLMs (hard, soft, LLM-as-judge) y cuándo usar cada una
- [ ] Entiendes qué es un golden dataset, por qué construirlo es inversión y no coste, y con qué frecuencia revisarlo
- [ ] Entiendes por qué el patrón Actor-Critic-Boss usa tres roles y no dos, y qué modos de fallo del Self-Refine puro resuelve el Boss
- [ ] Sabes cuándo el patrón Actor-Critic-Boss compensa (coste del error alto, criterios claros, latencia tolerable) y cuándo es overkill

## Documentación de referencia

- Madaan et al. — Self-Refine: Iterative Refinement with Self-Feedback (2023): https://arxiv.org/abs/2303.17651
- Shinn et al. — Reflexion: Language Agents with Verbal Reinforcement Learning (2023): https://arxiv.org/abs/2303.11366
- Estornell et al. — ACC-Collab (2024): https://arxiv.org/abs/2429.04XXXX
- Anthropic — Building Effective Agents: https://www.anthropic.com/research/building-effective-agents
- Anthropic — Files API documentation: https://docs.anthropic.com/en/docs/build-with-claude/files
- OpenAI — Files API documentation: https://platform.openai.com/docs/api-reference/files
- pypdf — Documentation: https://pypdf.readthedocs.io/
- PyMuPDF (fitz) — Documentation: https://pymupdf.readthedocs.io/
- Docling — Documentation: https://github.com/DS4SD/docling
- python-docx — Documentation: https://python-docx.readthedocs.io/
- Tavily — AI Search API: https://docs.tavily.com/
- DeepEval — LLM Evaluation Framework: https://docs.confident-ai.com/
- DeepEval — GEval metric: https://docs.confident-ai.com/docs/metrics-llm-evals
- Pydantic — Models: https://docs.pydantic.dev/latest/concepts/models/
- FastAPI — File uploads: https://fastapi.tiangolo.com/tutorial/request-files/
- JWT — Introduction: https://jwt.io/introduction
