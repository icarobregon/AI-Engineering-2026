# Sesión 15 — Puesta en producción de proyectos, arquitectura e infra

> 6️⃣ Módulo: Despliegue y puesta en producción · 77 min · 7 lecciones
> Proyecto 2 — sistema de estimación: backend de negocio (Ruby on Rails) + servicio IA (Python/FastAPI) + base de datos relacional (PostgreSQL) + base de datos vectorial.

## Objetivo de la sesión

Al cierre de la Sesión 14 el sistema de estimación está funcionalmente completo: recibe una transcripción, extrae requisitos, recupera presupuestos históricos de la base de datos vectorial, coordina a sus agentes con un supervisor construido a mano, se para cuando la confianza es baja y devuelve una estimación con su nivel de confianza y sus fuentes. Funciona. Y funciona exclusivamente en un sitio del mundo: vuestra máquina, con vuestras versiones, vuestras claves exportadas en el perfil de la shell y un orden de arranque que solo existe en vuestra cabeza. Eso no es un sistema: es una demo que sabéis conjurar.

La Sesión 15 elimina esa dependencia. El eje no es "subir el proyecto a un servidor", sino convertir cuatro exigencias que en local nadie os pedía en propiedades verificables del sistema: que arranque igual siempre en cualquier máquina, que sobreviva a que una pieza falle sin caerse entero, que sea operable por alguien que no lo escribió y que sea seguro por defecto desde el momento en que es alcanzable desde fuera. Producción no es una dirección IP; es ese conjunto de promesas, y se pueden romper las cuatro en la nube igual que se pueden cumplir en un servidor bajo la mesa.

De todas ellas hay una decisión que reordena la arquitectura entera y conviene fijar antes que ninguna otra: qué pieza mira a la calle y cuál no. La respuesta, para este sistema, no es negociable — el servicio IA nunca es público. Custodia la clave del proveedor de LLM (exponerlo es exponer vuestra factura) y por debajo de él viven las reglas de negocio que cualquiera podría saltarse hablándole directamente. Toda la sesión es, en buena medida, la mecánica de construir esa frontera y respetarla: primero documentando el sistema, después decidiendo por dónde se parte y qué contrato une las piezas, luego empaquetando cada una en una imagen reproducible, montando el pipeline que las construye y las mueve por los entornos, y por último materializando la frontera sobre redes reales en cloud.

Un detalle que atraviesa los seis artículos: no hay ningún paradigma nuevo. Reproducibilidad, separación de responsabilidades, contratos explícitos entre capas, no dejar secretos a la vista, pensar quién puede llamar a qué. Son las mismas buenas prácticas de siempre; lo único que cambia es que en local eran opcionales y en producción son la diferencia entre un sistema y una demo frágil.

## Qué vas a aprender

### 1. 📄 Qué entendemos por producción — 14 min

Arranca desmontando la intuición habitual: producción no es un lugar, es una promesa. O más bien cuatro. **Arrancar igual siempre**, en cualquier máquina y sin conocimiento tribal — si el arranque depende de que alguien recuerde un paso, ese paso es una bomba de relojería. **Sobrevivir a que una pieza falle** sin caerse entero: en local, si el proveedor de LLM da error lo veis en la terminal y reintentáis a mano; en producción no hay nadie mirando la terminal y el sistema tiene que degradar con criterio. **Ser operable por quien no lo escribió**, porque a las tres de la madrugada quien esté de guardia necesita saber qué mirar sin hacer ingeniería inversa. Y **ser seguro por defecto**, porque en el momento en que el sistema es alcanzable desde fuera deja de estar en un entorno de confianza.

**La decisión que lo cambia todo.** En local la pregunta "¿qué es alcanzable desde internet?" no existe: la respuesta es "nada, todo está en localhost". En producción es la primera decisión de diseño. El servicio IA no mira a la calle, nunca, y la razón es concreta: es quien custodia la clave del LLM, así que exponerlo es dejar que cualquiera que encuentre la URL gaste tokens contra vuestra tarjeta; y además las reglas de negocio —quién puede pedir una estimación, cuántas al día, con qué límites— viven en el backend de negocio, de modo que un servicio IA público permitiría saltárselas por debajo de toda la lógica de permisos. La topología se organiza alrededor de esa frontera: fuera, mirando a internet, solo el backend de negocio con su frontend, por HTTPS; dentro, en red privada, el servicio IA y las bases de datos. El backend de negocio cruza hacia dentro por HTTP interno autenticado con un token de servicio; nadie más la cruza.

**Tres capas que ahora se despliegan solas.** Tomarse en serio la frontera convierte la separación conceptual en tres unidades que se construyen, se versionan, se despliegan y se escalan por separado. Tiene sentido porque sus necesidades divergen: el servicio IA consume mucho y tarda segundos por petición, mientras el backend de negocio atiende un CRUD barato e instantáneo. Separados, se escala el que sufre sin tocar el otro y se cambia un prompt sin redesplegar la aplicación entera. Con una advertencia para no pasarse de frenada: "que se desplieguen solas" no significa fragmentar en veinte microservicios; son las tres capas y sus datastores, ni una pieza más de la que el sistema pida a gritos, porque la complejidad operativa de cada servicio nuevo se paga entera.

**Lo que queda por decidir.** Cinco cosas, que son los cinco tramos siguientes: documentar el sistema para que sobreviva a que os vayáis, fijar el contrato entre capas para poder cambiar una sin romper la otra, empaquetar cada pieza sin hornear un solo secreto dentro, montar un pipeline que testee sin gastar un token ni depender de la no-determinación del modelo, y materializar la frontera en redes de verdad, donde equivocarse tiene consecuencias que se pagan.

### 2. 📄 Documentar el sistema — 14 min

El punto de partida incómodo: **reproducible no es lo mismo que operable**. Un Dockerfile captura cómo se construye una imagen; no captura por qué el servicio IA está separado del backend de negocio, ni qué hacer cuando deja de responder de madrugada, ni cómo se interpreta una estimación con confianza 0.4. Todo eso está decidido — el problema es dónde está: en vuestra cabeza, donde no lo puede leer la persona de guardia, ni quien entre el mes que viene, ni vosotros dentro de seis meses.

**Por qué casi toda la documentación es mala.** Porque se trata "documentar el proyecto" como una tarea única e indiferenciada: un documento grande, escrito de una vez, para nadie en particular. Y un documento para nadie en particular no lo lee ni lo mantiene nadie en particular. El giro que lo arregla es dejar de preguntar "¿está documentado?" y preguntar "¿quién lo va a leer, y en qué momento?".

**Tres lectores, tres documentos.** Quien desarrolla o integra lee con el editor abierto y prisa por conectar su pieza: necesita documentación técnica (arquitectura de las tres capas, contrato entre ellas, modelos de datos, recorrido de una estimación). Quien opera lee durante una incidencia, con el sistema caído: no quiere entender la arquitectura, quiere saber qué comando ejecutar — necesita runbooks y procedimientos de escalado. Y quien usa el sistema lee mientras pide una estimación: necesita saber qué puede pedir y cómo interpretar lo que recibe. Un documento que intenta servir a los tres no sirve bien a ninguno.

**Automatizad todo lo que se pueda pudrir; escribid a mano solo lo que no se puede generar.** El enemigo de la documentación no es la pereza, es el tiempo: lo correcto hoy miente dentro de tres semanas, y una documentación que miente es peor que ninguna porque la gente le hace caso. Por eso la mejor documentación técnica es la que no escribís: si definís los endpoints del servicio IA con modelos Pydantic (`EstimateRequest`, `EstimateResponse`), FastAPI genera el esquema OpenAPI y la interfaz navegable en `/docs` sin una línea escrita, y no puede desincronizarse porque *es* el modelo. Lo mismo con los diagramas como código (Mermaid, PlantUML) versionados junto al repo, para que arquitectura y diagrama viajen en el mismo commit. Lo que no se puede generar es el porqué: por qué separasteis el servicio IA, por qué búsqueda síncrona, por qué un token de servicio. Eso merece un registro breve de decisiones de arquitectura (ADR), cada una con su motivo.

**El runbook es una lista para el pánico, no un manual.** No explica teoría ni razona: dice qué mirar, qué comando lanzar y qué esperar, y está pensado para ejecutarse bajo presión por alguien que puede no saber nada de embeddings. Su valor no se mide el día que se escribe, sino el día que todo está en llamas.

**Documentación de usuario: enseñar a leer el número.** En este sistema el trabajo principal no es enseñar a usar la aplicación, sino a interpretar lo que devuelve. Una estimación no es un dato objetivo, es una respuesta con incertidumbre: hay que enseñar a leer la confianza, a mirar las fuentes y, sobre todo, a entender que "no tengo datos suficientes para estimar esto" no es un error sino el sistema comportándose bien. Un usuario que trata una confianza de 0.3 como una certeza es un problema de documentación, no de modelo.

### 3. 📄 Partir en servicios — 13 min

La implementación de referencia toma una decisión que de lejos parece contradictoria: mantiene el frontend y el backend de negocio juntos en un único proyecto Rails —un solo deploy, sin contrato REST interno— y en cambio saca el servicio IA a un proceso aparte en Python, con su frontera, su contrato y su clave. Tres piezas conceptuales, dos servicios. Entender por qué esa línea y no otra es entender cuándo partir un sistema.

**Separar cuesta, y el peaje es para siempre.** Cada frontera introduce un salto de red donde antes había una llamada a función (lo instantáneo e infalible pasa a tardar milisegundos y a poder fallar: timeouts, reintentos, el otro lado caído), un contrato que mantener sincronizado entre dos lados que deben evolucionar sin romperse, dos despliegues que coordinar y una superficie de fallo mayor. Si una frontera no compra nada que compense ese peaje es teatro de arquitectura, y el teatro de arquitectura se paga en latencia, en coste y en madrugadas depurando.

**Cuatro cosas que un corte puede comprar.** La decisiva para el servicio IA es **lenguaje distinto**: todo el ecosistema de IA —clientes de LLM, librerías de embeddings, frameworks de agentes— vive en Python, y no se mete dentro de un proceso Rails; no es una preferencia, es que la alternativa no existe. Las otras tres refuerzan el mismo corte: **escalado independiente** (una estimación consume mucho y tarda segundos, un CRUD es barato e instantáneo), **despliegue independiente** (cambiar un prompt o la lógica RAG sin redesplegar toda la aplicación de negocio) y **aislamiento de fallos** (si el proveedor de LLM cae, el servicio IA se degrada pero el backend de negocio sigue en pie). Entre frontend y backend de negocio no hay ninguno de esos cuatro ejes: comparten lenguaje, datos y ritmo de cambio, y no hay frontera de seguridad entre medias — meter un contrato REST ahí sería pagar el peaje entero sin comprar nada. La regla: separad por los ejes que de verdad divergen (lenguaje, escalado, ritmo de cambio, frontera de seguridad), no por dibujar un diagrama más simétrico.

**El contrato es la frontera hecha código.** Tres decisiones marcan la diferencia entre un contrato que aguanta y uno que se rompe al primer cambio. *Versionad desde el día uno* con prefijo `/v1/`, para que el día que haya un cambio incompatible `/v2/` conviva con `/v1/` mientras se migra. *Payloads explícitos y validados*: un `EstimateRequest` tipado con Pydantic de entrada y un `EstimateResponse` igual de explícito de salida, nada de diccionarios ambiguos que cada lado interpreta a su manera. Y *los errores son parte del contrato*: 422 si la entrada es inválida, 401 si el token de servicio es incorrecto, 503 si una dependencia (el LLM o la BBDD vectorial) no está disponible — el backend de negocio necesita distinguirlos para reintentar, degradar o avisar; un contrato que solo define el éxito obliga al otro lado a adivinar ante el fracaso. Todo ello viaja por la red interna y autenticado con el token de servicio: el contrato no es solo qué datos cruzan, también quién tiene permiso para llamar.

**Síncrono hasta que duela.** Una estimación con RAG y agentes tarda segundos, no milisegundos. Por defecto el backend de negocio llama y espera, con timeouts sensatos: si el servicio IA no responde en X segundos hay que cortar y degradar, no quedarse colgado arrastrando peticiones web detrás. La opción asíncrona —encolar, devolver un identificador y consultar después por polling o recibir un webhook— aparece cuando la latencia o la concurrencia lo exigen de verdad, y cuesta una cola, un worker y estado del trabajo que gestionar. Montar colas "por si acaso" para un sistema que responde en dos segundos es pagar un peaje que nadie os está cobrando.

**Cuándo no partir.** Si dos piezas comparten lenguaje, datos y ritmo de cambio, no las separéis. Si el problema es que un proceso es lento, un servicio nuevo no lo acelera: lo reparte y le añade un salto de red encima. Y no fragmentéis en microservicios porque suene maduro: cada servicio de más es un sitio más donde algo falla, un contrato más que mantener y un despliegue más que coordinar.

### 4. 📄 Contenerización con Docker — 12 min

"Pues en mi máquina funciona" suena a excusa, pero es una confesión: lo que hace que el sistema funcione no está en el código, está en vuestra máquina — una versión de Python instalada hace meses, una librería que está ahí de casualidad, una variable de entorno que exportasteis y olvidasteis. Un sistema que solo arranca en un sitio del mundo no está listo para producción.

**Un contenedor es vuestra máquina, empaquetada.** Empaqueta la aplicación con su runtime, sus librerías y su configuración en una imagen reproducible: en vez de esperar que la máquina de destino tenga lo correcto instalado, os lleváis lo correcto dentro. La imagen que corre en el portátil es, bit a bit, la que corre en staging y en producción. Para un sistema con IA no es comodidad sino casi necesidad: el servicio IA depende de un ecosistema de Python especialmente sensible a versiones (cliente del proveedor de LLM, librerías de embeddings, drivers de la base de datos vectorial) donde un cambio menor puede alterar el comportamiento o romper el arranque.

**Tres costumbres que parecen manías y no lo son.** Instalar las dependencias antes de copiar el código, para que Docker reutilice esa capa y no reinstale medio mundo cada vez que cambia una línea. Partir de imágenes slim, porque una imagen pequeña se despliega antes y ofrece menos superficie de ataque. Y definir un healthcheck, para que el sistema sepa si el contenedor está realmente listo y no solo "arrancado".

**Una imagen se comparte; un secreto dentro se filtra.** Los secretos no van dentro de la imagen, nunca. Una imagen es un artefacto pensado para compartirse: se sube a un registro, se la baja un compañero, se despliega en varios sitios. Si horneáis la clave del LLM dentro, viaja con ella a todas partes y queda en el historial de capas aunque luego la "borréis": un secreto dentro de una imagen es un secreto con pasaporte. Lo correcto es que la imagen no sepa nada de las claves — entran en tiempo de ejecución como variables de entorno, de modo que la misma imagen corre en dev con unas y en producción con otras. En el repositorio solo vive un `.env.example` con los nombres, nunca los valores.

**docker-compose: el sistema entero con un comando.** Dos ideas hacen que el fichero esté bien montado. *Solo el backend de negocio publica un puerto al host* — es la frontera hecha configuración; dentro de la red interna los servicios se encuentran por su nombre de servicio (`ai-service`, `vector-db`), no por `localhost`, y si por error le ponéis un puerto al servicio IA acabáis de abrir a internet la pieza que custodia la clave del LLM. *El arranque tiene orden*: con `depends_on` y healthchecks cada servicio espera a que sus dependencias estén sanas, no solo lanzadas — la diferencia entre "el proceso existe" y "el proceso está listo para trabajar".

**Lo que el contenedor no arregla.** Os da reproducibilidad, no corrección: si hay un bug, ahora lo reproduciréis idénticamente en todas partes. Y dos trampas siguen siendo vuestras: los datos, porque un contenedor es efímero por diseño y la base de datos vectorial que costó tiempo y tokens poblar tiene que vivir en un volumen persistente o un redeploy la borra; y los secretos, porque la disciplina de no hornearlos no la impone el contenedor.

### 5. 📄 CI/CD con tokens — 12 min

La regla que descoloca a todo el mundo la primera vez: **la integración continua de vuestro sistema de IA no debe llamar a la IA**. No es una boutade; es que hay dos actividades que se confunden —testear vuestro código y evaluar el modelo— y el pipeline solo debe hacer una.

**Por qué el modelo no puede entrar en CI.** Un test de CI tiene un trabajo: dar siempre la misma respuesta ante el mismo código. Una llamada al modelo rompe esa propiedad por tres sitios. Rompe el *determinismo*: el mismo prompt puede dar respuestas distintas en dos ejecuciones seguidas, y un test que a veces pasa y a veces no es una moneda al aire con aspecto de test — lo peor que le puede pasar a un equipo, porque enseña a ignorar los rojos. Rompe el *coste*: cada push, en cada rama, gastaría tokens de verdad; la factura crece con la actividad de desarrollo, no con el uso del producto, y acabáis pagando por tener miedo a hacer commit. Y rompe la *velocidad*: una llamada al modelo tarda segundos, un test unitario debería tardar milisegundos, y un CI lento es un CI que la gente evita.

**Mockear el modelo es testear lo vuestro, no lo suyo.** No es trabajo de CI comprobar si el modelo estima bien — eso es evaluación, con sus golden sets y sus métricas, y es materia de la sesión siguiente. CI testea todo lo vuestro que rodea al modelo: que el prompt se construye con los datos correctos, que el output se parsea bien, que un JSON malformado no revienta el servicio, que un 503 de la BBDD vectorial se maneja como toca, que el contrato `/v1/` sigue devolviendo lo que el backend de negocio espera. Nada de eso necesita el modelo real: solo una respuesta fija en su lugar. A eso se suman los *contract tests*, que verifican que el servicio IA respeta el contrato esperado para que la frontera no se rompa en silencio.

**El smoke test es donde el modelo sí entra.** Después de desplegar —no en cada commit— se ejecuta una comprobación mínima de que el sistema desplegado está vivo y responde con la forma correcta: que `/health` contesta y que una estimación de prueba recorre el flujo completo. Este sí toca el sistema real, modelo incluido, porque su pregunta no es "¿el código está bien?" sino "¿el despliegue funciona de punta a punta?". CI es determinista, mockeado y corre en cada commit; el smoke test es real, escaso y corre después de desplegar. Confundirlos produce pipelines lentos, caros e inútiles.

**Una imagen, tres entornos.** Dev, staging y producción corren *la misma imagen*; lo único que cambia es la configuración. Es el principio 12-factor: el artefacto se construye una vez y lo que varía entre entornos son las variables de entorno — la clave del LLM, las URLs de las bases de datos, el nivel de logging. Y eso ata el último cabo sobre los secretos: en el pipeline las claves no viven en el repositorio ni aparecen en los logs de la ejecución; se guardan en el gestor de secretos de la plataforma de CI/CD y del proveedor cloud, y se inyectan como variables de entorno en el despliegue. Un secreto que aparece en un log de pipeline es un secreto quemado, igual que uno horneado en una imagen.

### 6. 📄 Despliegue en clouds — 12 min

**Elegir dónde: la herramienta más simple que resuelva el problema.** Las opciones se ordenan de más simple a más potente, que casi siempre significa también de más simple a más complejo de operar: en un extremo los PaaS de contenedores (Render, Railway, Fly y similares), a los que les das tu imagen y se encargan de casi toda la infraestructura; en el medio los contenedores gestionados del proveedor cloud, con más control y más configuración; en el otro extremo Kubernetes, máxima flexibilidad y máxima complejidad operativa. Para tres capas y sus datastores, un PaaS de contenedores es suficiente. Kubernetes aquí no es "hacerlo bien": es sobreingeniería, el mismo error que fragmentar en microservicios. Elegir la opción simple no es conformarse: es reservar la complejidad para donde importa, que en un sistema de IA no es la infraestructura sino la calidad y el coste de las respuestas.

**Materializar la frontera en redes reales.** El backend de negocio es lo único público: se expone tras HTTPS, con su dominio, como puerta de entrada. El servicio IA va en la red privada del proveedor, sin dirección pública, alcanzable solo desde el backend de negocio y autenticado con el token de servicio. Las bases de datos, relacional y vectorial, también privadas, sean servicios gestionados o contenedores con almacenamiento persistente. Y los secretos llegan del gestor de secretos de la plataforma, inyectados en el despliegue, nunca en la imagen ni en el repositorio. No hay ninguna idea nueva: es la frontera del primer artículo aterrizada. Lo único que cambia es que un descuido —una casilla de "público" marcada por defecto, un datastore expuesto para "probar rápido"— ya no lo ve solo vuestro localhost.

**El health check tiene que ser barato y no llamar al modelo.** El proveedor lo usa para dos cosas distintas —saber si una instancia está lista para recibir tráfico (readiness) y si sigue viva o hay que reiniciarla (liveness)— y lo consulta constantemente. Si el healthcheck gastara tokens estaríais pagando por cada comprobación, muchas veces por minuto, para siempre. Y peor: si dependiera de que el proveedor de LLM responda, un hipo suyo haría fallar el healthcheck y la plataforma reiniciaría la instancia o le cortaría el tráfico — un sistema que se autodestruye cada vez que el LLM tose. El `/health` solo debe responder que la aplicación está viva y, como mucho, que sus dependencias internas contestan. Comprobar la calidad de las respuestas es trabajo de la monitorización, no del latido.

**Dos trampas que solo aparecen en cloud.** La *persistencia*: un redeploy puede recrear el contenedor desde cero, así que si la base de datos vectorial no vive en almacenamiento persistente con backups, un despliegue rutinario borra el conocimiento del sistema. Y el *arranque en frío y la latencia*: el servicio IA puede tardar en estar listo si carga modelos de embeddings al arrancar, y la región donde despleguéis determina la latencia contra el proveedor de LLM.

**Cierre.** El sistema queda documentado para que otro lo opere, partido por las fronteras que compran algo con un contrato explícito, empaquetado en imágenes reproducibles, construido y probado por un pipeline que no gasta un token, y desplegado con la frontera público/privado materializada en redes reales. Las cuatro promesas del primer artículo, cumplidas. Queda una pregunta que el despliegue no responde: ¿está funcionando *bien*? Sabéis que está vivo, no si estima con acierto, si ha empezado a alucinar desde el último cambio de prompt ni cuánto cuesta cada respuesta. Poner ojos a lo desplegado —evaluación, observabilidad, safety y control de costes: LLMOps— es la sesión siguiente.

## Ejercicios prácticos

### ✍️ Ejercicio pre-sesión — Dockerización del proyecto

🚨 **Fecha límite indicada en la plataforma: lunes 20 de septiembre a las 23:59 de tu hora local.** El criterio operativo del programa es entregar al menos dos días antes de la sesión en vivo: las entregas posteriores no entran en la revisión. Tiempo estimado del enunciado: 5 min. Punto de partida: el repositorio del Proyecto 2 tal como quedó tras la Sesión 14. Repositorio de referencia: https://github.com/LIDR-academy/ai-engineering. Autor del enunciado: Antonio Pérez.

#### Contexto

Hasta ahora el Proyecto 2 se arranca a mano: una terminal para el backend de negocio (Rails), otra para el servicio IA (FastAPI), y por tu cuenta la base de datos relacional y la vectorial. Sirve para desarrollar, pero no es reproducible ni desplegable: depende de tu máquina, de tus versiones y de que recuerdes el orden de arranque. En este ejercicio vas a containerizar el proyecto como microservicios separados y orquestarlos con docker-compose, de forma que todo el sistema arranque con un único comando y las tres capas se comuniquen entre contenedores. Es el paso previo imprescindible para el despliegue en cloud del directo.

Nomenclatura del programa: **servicio IA** es el backend Python/FastAPI (encapsula CAG/RAG y agentes) y **backend de negocio** es la capa Rails (usuarios, sesiones, persistencia, reglas de negocio). Se evita la palabra "backend" a secas porque hay dos.

#### Objetivo

Un `docker-compose.yml` que levante cuatro piezas:

| Servicio | Rol | Exposición |
| --- | --- | --- |
| backend de negocio (Rails) | único punto de entrada público | publicado al host (`3000:3000`) |
| servicio IA (FastAPI) | CAG/RAG, agentes, clave del LLM | **solo red interna**, nunca publicado al host |
| base de datos relacional (PostgreSQL) | datastore del backend de negocio | solo red interna |
| base de datos vectorial | datastore del servicio IA (el motor que ya uses) | solo red interna |

Y que una estimación end-to-end (usuario → backend de negocio → servicio IA → BBDD vectorial → respuesta) funcione íntegramente dentro de los contenedores.

#### Requisitos previos

- Docker y Docker Compose instalados (`docker --version`, `docker compose version`).
- El repositorio del Proyecto 2 tal como quedó tras la Sesión 14.
- La clave de API del proveedor de LLM disponible como variable de entorno (nunca escrita en un fichero versionado).

#### Paso 1 — Estructura de carpetas

Cada servicio debe ser autocontenido:

```
project-2/
├── business-backend/     # Rails app (frontend + backend de negocio)
│   └── Dockerfile
├── ai-service/           # FastAPI app (servicio IA)
│   └── Dockerfile
├── .env.example          # plantilla de variables (SÍ se versiona)
├── .env                  # valores reales (NO se versiona)
└── docker-compose.yml
```

Añade `.env` a tu `.gitignore` si no está ya.

#### Paso 2 — Dockerfile del servicio IA (Python / FastAPI)

```dockerfile
# ai-service/Dockerfile
FROM python:3.12-slim

# Avoid interactive prompts and keep the image small
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first to leverage layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

EXPOSE 8000

# Healthcheck hits a lightweight endpoint that does NOT call the LLM
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Expon un endpoint `/health` que responda sin llamar al LLM:

```python
# ai-service/app/main.py (extract)
from fastapi import FastAPI

app = FastAPI(title="AI Service", version="1.0.0")

@app.get("/health")
def health() -> dict:
    # Liveness only — must be cheap and must NOT call the LLM
    return {"status": "ok"}
```

#### Paso 3 — Dockerfile del backend de negocio (Rails)

```dockerfile
# business-backend/Dockerfile
FROM ruby:3.3-slim

ENV RAILS_ENV=production \
    BUNDLE_WITHOUT="development:test"

# System packages needed to build gems and run Rails
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends build-essential libpq-dev nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY Gemfile Gemfile.lock ./
RUN bundle install

COPY . .

# Precompile assets at build time (adjust if you use a JS bundler)
RUN bundle exec rake assets:precompile

EXPOSE 3000

CMD ["bin/rails", "server", "-b", "0.0.0.0", "-p", "3000"]
```

El patrón es independiente del stack: si tu backend de negocio no es Rails, aplica el mismo esquema (instalar dependencias, copiar código, exponer el puerto, arrancar el servidor). Lo relevante es que el contenedor sea autocontenido.

#### Paso 4 — Variables de entorno

```dotenv
# .env.example

# LLM provider
LLM_API_KEY=

# AI service
AI_SERVICE_PORT=8000

# Internal service-to-service auth (business backend -> AI service)
AI_SERVICE_TOKEN=change-me

# Relational DB
POSTGRES_USER=app
POSTGRES_PASSWORD=change-me
POSTGRES_DB=estimation

# How the business backend reaches the AI service (internal DNS name)
AI_SERVICE_URL=http://ai-service:8000
```

Copia `.env.example` a `.env` y rellena los valores reales en local. Dentro de compose los servicios se resuelven por su **nombre de servicio**, no por `localhost`.

#### Paso 5 — docker-compose.yml

Punto clave de seguridad: el servicio IA **no publica puertos al host** (no lleva `ports:`), solo es alcanzable por la red interna; el único servicio con `ports:` es el backend de negocio.

```yaml
# docker-compose.yml
services:
  business-backend:
    build: ./business-backend
    ports:
      - "3000:3000"          # public entry point
    environment:
      DATABASE_URL: postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      AI_SERVICE_URL: ${AI_SERVICE_URL}
      AI_SERVICE_TOKEN: ${AI_SERVICE_TOKEN}
    depends_on:
      postgres:
        condition: service_healthy
      ai-service:
        condition: service_healthy

  ai-service:
    build: ./ai-service
    # No "ports:" on purpose — internal only, not reachable from the host
    environment:
      LLM_API_KEY: ${LLM_API_KEY}
      AI_SERVICE_TOKEN: ${AI_SERVICE_TOKEN}
      VECTOR_DB_URL: http://vector-db:6333
    depends_on:
      - vector-db

  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5

  vector-db:
    image: qdrant/qdrant:latest    # replace with the vector engine you use
    volumes:
      - vector_data:/qdrant/storage

volumes:
  postgres_data:
  vector_data:
```

Sustituye la imagen de `vector-db` y el `VECTOR_DB_URL` por el motor vectorial que ya utilices (Qdrant, Chroma, pgvector sobre el propio Postgres, etc.). Si usas pgvector, la BBDD vectorial y la relacional pueden ser el mismo contenedor.

#### Paso 6 — Autenticación entre servicios

El servicio IA no debe aceptar peticiones de cualquiera solo por estar en la red interna:

```python
# ai-service/app/security.py
import os
from fastapi import Header, HTTPException

EXPECTED_TOKEN = os.environ["AI_SERVICE_TOKEN"]

def verify_service_token(x_service_token: str = Header(...)) -> None:
    if x_service_token != EXPECTED_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid service token")
```

Protege el endpoint de estimación con esa dependencia; `/health` se deja sin proteger para que el healthcheck funcione. Desde el backend de negocio, la llamada incluye el token (el patrón es independiente del stack):

```ruby
# business-backend/app/clients/ai_service_client.rb
require "net/http"
require "json"

class AiServiceClient
  def initialize
    @base_url = ENV.fetch("AI_SERVICE_URL")
    @token = ENV.fetch("AI_SERVICE_TOKEN")
  end

  def estimate(payload)
    uri = URI("#{@base_url}/v1/estimate")
    request = Net::HTTP::Post.new(uri)
    request["Content-Type"] = "application/json"
    request["X-Service-Token"] = @token
    request.body = payload.to_json

    response = Net::HTTP.start(uri.host, uri.port) { |http| http.request(request) }
    JSON.parse(response.body)
  end
end
```

#### Paso 7 — Arrancar y verificar

```bash
docker compose build
docker compose up
```

Las cinco comprobaciones que hay que superar:

1. `docker compose ps` muestra los cuatro servicios arriba y `ai-service` / `postgres` en estado `healthy`.
2. Desde el host, http://localhost:3000 sirve el frontend del backend de negocio.
3. Desde el host, el servicio IA **no** es accesible directamente (no hay puerto publicado): verifica que http://localhost:8000 no responde.
4. Una estimación lanzada desde la interfaz recorre el flujo completo y devuelve un resultado coherente: backend de negocio → servicio IA (con token) → BBDD vectorial → respuesta.
5. `docker compose down && docker compose up` y el sistema vuelve a funcionar sin pasos manuales (persistencia de datos vía volúmenes).

#### Entregables

Sube al repositorio del Proyecto 2:

- `ai-service/Dockerfile` y `business-backend/Dockerfile`.
- `docker-compose.yml`.
- `.env.example` con todas las variables necesarias (sin valores reales).
- Endpoint `/health` en el servicio IA y verificación de token de servicio.
- Un README corto (`docs/deployment-local.md`) con el comando de arranque y las 5 comprobaciones anteriores.

No subas tu `.env` ni ninguna clave real.

Envía por correo a george@lidr.co el enlace a la rama (URL completa de GitHub) y el enlace o captura de una ejecución completa de `docker compose up` mostrando las cinco comprobaciones del Paso 7, al menos dos días antes de la sesión en vivo. Las entregas posteriores no entran en la revisión.

#### Cómo llegar preparado al directo

Trae anotado qué **no** te funcionó: errores de build, problemas de networking entre contenedores, servicios que arrancan en mal orden, el servicio IA inalcanzable o alcanzable cuando no debería. El primer bloque del directo (15 min) sirve precisamente para resolver estos problemas en común antes de pasar al despliegue en cloud. Si te bloqueas del todo, en el repositorio de la solución hay una versión funcional de referencia: inténtalo primero por tu cuenta y úsala como último recurso o para contrastar.

#### Criterios de aceptación ("hecho")

- Los cuatro servicios levantan con un único `docker compose up`, sin pasos manuales previos.
- Solo el backend de negocio publica puerto al host; el servicio IA y los datastores son inalcanzables desde fuera.
- El servicio IA expone `/health` sin autenticación y sin llamar al LLM, y el healthcheck del contenedor lo usa.
- El endpoint de estimación del servicio IA exige el token de servicio (401 si falta o es incorrecto).
- El backend de negocio alcanza al servicio IA por nombre de servicio (`http://ai-service:8000`), no por `localhost`.
- Ningún secreto vive en el repositorio ni dentro de una imagen: solo `.env.example` con nombres, valores inyectados por entorno.
- Los datos sobreviven a `docker compose down && up` gracias a los volúmenes.
- Una estimación end-to-end funciona íntegramente dentro de los contenedores.

#### Pitfalls comunes

- **Publicar el puerto del servicio IA.** Es el error grave: abre a internet la pieza que custodia la clave del LLM y permite saltarse las reglas de negocio. El servicio IA no lleva `ports:` jamás.
- **Usar `localhost` entre contenedores.** Dentro de compose cada servicio se resuelve por su nombre (`ai-service`, `postgres`, `vector-db`); `localhost` dentro de un contenedor es ese mismo contenedor.
- **Hornear secretos en la imagen o en el `Dockerfile`.** Viajan al registro y quedan en el historial de capas. Entran por entorno, en tiempo de ejecución.
- **Versionar el `.env`.** Solo se versiona `.env.example`, con nombres y sin valores. Añade `.env` al `.gitignore`.
- **`depends_on` sin `condition: service_healthy`.** Solo garantiza orden de lanzamiento, no que la dependencia esté lista; el servicio arranca contra una base de datos que aún no acepta conexiones.
- **Healthcheck que llama al LLM.** Gasta tokens en cada comprobación y convierte un hipo del proveedor en reinicios en cascada. `/health` barato y sin autenticación.
- **Proteger `/health` con el token.** El healthcheck del contenedor no lo envía y el servicio se marcará como unhealthy para siempre.
- **No persistir la BBDD vectorial.** Sin volumen, un `docker compose down -v` o un redeploy borra el corpus que costó tiempo y tokens generar.
- **Copiar el código antes que las dependencias.** Invalida la caché de capas en cada cambio de una línea y hace los builds eternos.
- **Confundir reproducibilidad con corrección.** El contenedor garantiza que el mismo código se comporta igual en todas partes, no que el código esté bien.
- **Fragmentar de más.** Son dos servicios de aplicación más sus datastores. Cada servicio extra es un contrato, un despliegue y una superficie de fallo más.
- **Llamar al modelo real en CI.** No determinista, caro y lento: mockea el LLM en los tests y deja el modelo real para el smoke test posterior al despliegue.

### 🛠️ Contexto técnico para la implementación

Material de referencia consolidado de los seis artículos y del enunciado, con todo lo necesario para implementar la contenerización con Claude Code CLI. Todo el código, nombres, docstrings y logs en inglés.

#### Invariantes de arquitectura (no negociables)

1. **Frontera público/privado.** Solo el backend de negocio mira a internet. Servicio IA, BBDD relacional y BBDD vectorial viven en red privada. Esta regla se aplica igual en `docker-compose` (quién lleva `ports:`) que en cloud (quién tiene dominio público).
2. **El servicio IA custodia la clave del LLM.** Nunca sale del contenedor ni de la red privada, nunca entra en una imagen ni en el repositorio.
3. **Autenticación de servicio a servicio.** Cabecera `X-Service-Token` compartida por entorno; el endpoint de estimación la exige, `/health` no.
4. **Contrato estable y versionado.** `/v1/estimate`, payloads Pydantic (`EstimateRequest` / `EstimateResponse`), errores explícitos: 422 entrada inválida, 401 token incorrecto, 503 dependencia caída.
5. **Una imagen, varios entornos.** El artefacto se construye una vez; dev, staging y producción solo cambian variables de entorno (12-factor).
6. **Estado fuera del contenedor.** Todo dato que deba sobrevivir a un redeploy vive en un volumen o servicio gestionado.

#### Estructura de módulos objetivo

```
project-2/
├── ai-service/
│   ├── Dockerfile
│   ├── requirements.txt          # o pyproject.toml / uv.lock
│   ├── app/
│   │   ├── main.py               # FastAPI app + /health + routers
│   │   ├── security.py           # verify_service_token()
│   │   ├── api/routers/          # /v1/estimate (protegido por el token)
│   │   └── domain/               # CAG/RAG, grafo y agentes (S12-S14)
│   └── tests/
│       └── test_estimation.py    # LLM mockeado, sin red
├── business-backend/
│   ├── Dockerfile
│   └── app/clients/ai_service_client.rb
├── docs/
│   ├── deployment-local.md       # arranque + las 5 comprobaciones
│   ├── architecture.md           # tres capas, frontera, contrato
│   ├── runbooks/                 # listas para el pánico
│   └── adr/                      # decisiones de arquitectura y su porqué
├── .github/workflows/ci.yml      # build + tests mockeados + smoke post-deploy
├── .env.example
└── docker-compose.yml
```

#### Test de CI con el modelo mockeado

```python
# ai-service/tests/test_estimation.py
from unittest.mock import patch

def test_estimate_parses_model_output():
    fake_completion = '{"estimate_points": 5, "confidence": 0.8, "sources": ["task-42"]}'
    with patch("app.llm.client.complete", return_value=fake_completion):
        result = estimation_pipeline.run(EstimateRequest(
            task_description="Add OAuth login",
            project_id="proj-1",
        ))
    assert result.estimate_points == 5
    assert 0 <= result.confidence <= 1
```

El test no comprueba si 5 puntos es una buena estimación —eso es evaluación— sino que el código convierte correctamente la respuesta del modelo en un `EstimateResponse` válido. Determinista, instantáneo y gratis.

#### Runbook mínimo (documentación operativa)

```markdown
## Runbook: el servicio IA no responde

Síntoma: el backend de negocio devuelve 502/timeout al estimar.

1. Estado del contenedor: docker compose ps ai-service
2. Healthcheck: debe estar en estado `healthy`.
3. Últimos logs: docker compose logs --tail=100 ai-service
4. Causas frecuentes:
   - LLM_API_KEY caducada -> rotar clave (ver runbook de rotación).
   - BBDD vectorial caída -> ver runbook de BBDD vectorial.
5. Reinicio seguro (no afecta al backend de negocio):
   docker compose restart ai-service
6. Si persiste, escalar a guardia con el ID de la petición.
```

Sin prosa, sin contexto, sin teoría: pasos. La calma para entender el porqué va en la documentación técnica.

#### Comandos de referencia

```bash
# Construir y levantar el sistema completo
docker compose build
docker compose up

# Estado y salud de los servicios
docker compose ps
docker compose logs --tail=100 ai-service

# Comprobar la frontera: el servicio IA NO debe responder desde el host
curl -sS -m 3 http://localhost:8000/health || echo "OK: ai-service no es alcanzable desde el host"

# Comprobar /health desde dentro de la red interna
docker compose exec business-backend curl -sS http://ai-service:8000/health

# Llamada autenticada al contrato del servicio IA (desde la red interna)
docker compose exec business-backend curl -sS -X POST http://ai-service:8000/v1/estimate -H 'Content-Type: application/json' -H "X-Service-Token: $AI_SERVICE_TOKEN" -d '{"task_description": "Add OAuth login", "project_id": "proj-1"}'

# Documentación autogenerada del contrato (solo en dev)
# http://localhost:8000/docs  -> requiere exponer el puerto temporalmente; en produccion NO

# Reinicio limpio conservando volúmenes
docker compose down && docker compose up -d

# Tests deterministas, sin red y sin clave
docker compose exec ai-service pytest -v
```

#### Qué verificar (y qué no)

Verifica propiedades del sistema, no la calidad del modelo: que los cuatro contenedores quedan `healthy`, que el puerto 8000 no responde desde el host, que una llamada sin `X-Service-Token` devuelve 401, que una entrada inválida devuelve 422, que con la BBDD vectorial parada el servicio IA devuelve 503 y el backend de negocio degrada en vez de reventar, y que tras `down && up` los datos siguen ahí. La calidad de las estimaciones es evaluación, y es materia de la sesión siguiente.

#### Qué se añade en el directo (fuera del alcance de la pre-sesión)

- Resolución en común de los problemas de contenerización (primer bloque, ~15 min): errores de build, networking entre contenedores, orden de arranque, exposición indebida del servicio IA.
- Despliegue en cloud sobre un PaaS de contenedores: backend de negocio público tras HTTPS, servicio IA y datastores en red privada, secretos desde el gestor del proveedor.
- Pipeline de CI/CD completo: build de imágenes, tests con el modelo mockeado, promoción del mismo artefacto por dev/staging/producción y smoke test posterior al despliegue.
- Persistencia gestionada de la BBDD vectorial, backups, arranque en frío y elección de región.

## Checklist antes de la siguiente sesión

- Sabes defender que producción no es un lugar sino cuatro promesas: arrancar igual siempre, sobrevivir a fallos parciales, ser operable por quien no lo escribió y ser seguro por defecto.
- Tienes clara la frontera público/privado y por qué el servicio IA nunca es alcanzable desde internet (clave del LLM y reglas de negocio).
- Entiendes las tres capas como unidades desplegables independientes, y sabes argumentar por qué no hay que fragmentar más.
- Distingues los tres tipos de documentación por lector y momento: técnica, operativa y de usuario.
- Automatizas lo que se puede pudrir (OpenAPI desde Pydantic, diagramas como código) y escribes a mano solo el porqué (ADR) y el pánico (runbooks).
- Tienes al menos un runbook escrito como lista ejecutable bajo presión, sin prosa.
- Sabes enumerar el peaje de cada frontera (salto de red, contrato, dos despliegues, más superficie de fallo) y las cuatro cosas que puede comprar (lenguaje, escalado, ritmo de cambio, seguridad).
- Tu contrato está versionado (`/v1/`), con payloads tipados y con los errores como parte explícita del acuerdo (422 / 401 / 503).
- Empiezas por comunicación síncrona con timeouts sensatos y sabes cuándo justificarías pasar a asíncrono.
- Cada servicio tiene su Dockerfile con dependencias antes que código, imagen slim y healthcheck.
- Ningún secreto vive dentro de una imagen ni en el repositorio: solo `.env.example` y variables de entorno en tiempo de ejecución.
- Tu `docker-compose.yml` publica un único puerto (el del backend de negocio) y usa nombres de servicio, `depends_on` y healthchecks.
- La BBDD vectorial persiste en un volumen y sobrevive a `down && up`.
- Sabes explicar por qué CI no debe llamar al modelo (determinismo, coste, velocidad) y qué sí testea CI.
- Tienes tests con el LLM mockeado y sabes qué es un contract test.
- Distingues CI (determinista, mockeado, en cada commit) de smoke test (real, escaso, tras el despliegue).
- Aplicas 12-factor: una imagen para los tres entornos, la configuración en el entorno.
- Eliges la herramienta de despliegue más simple que resuelva el problema y sabes por qué Kubernetes aquí no compra nada.
- Tu `/health` es barato, no está autenticado y no llama al modelo; sabes la diferencia entre readiness y liveness.
- Tienes en el radar las dos trampas de cloud: persistencia ante redeploy y arranque en frío / latencia por región.
- Entregable enviado a george@lidr.co con al menos dos días de antelación: enlace a la rama y evidencia de `docker compose up` con las cinco comprobaciones.

## Documentación de referencia

**Docker y orquestación local**

- Docker — referencia del Dockerfile: https://docs.docker.com/reference/dockerfile/
- Docker — buenas prácticas para escribir Dockerfiles: https://docs.docker.com/build/building/best-practices/
- Docker Compose — referencia del fichero Compose: https://docs.docker.com/reference/compose-file/
- Docker Compose — control del orden de arranque (`depends_on`, healthchecks): https://docs.docker.com/compose/how-tos/startup-order/
- Docker — gestión de volúmenes y persistencia: https://docs.docker.com/engine/storage/volumes/

**Servicio IA, contrato y documentación**

- FastAPI — despliegue en contenedores: https://fastapi.tiangolo.com/deployment/docker/
- FastAPI — OpenAPI y documentación autogenerada: https://fastapi.tiangolo.com/tutorial/metadata/
- FastAPI — dependencias y seguridad por cabecera: https://fastapi.tiangolo.com/tutorial/dependencies/
- Pydantic — modelos y validación: https://docs.pydantic.dev/latest/
- Especificación OpenAPI: https://spec.openapis.org/oas/latest.html
- Mermaid — diagramas como código: https://mermaid.js.org/intro/

**Pipeline, entornos y secretos**

- The Twelve-Factor App: https://12factor.net/
- GitHub Actions — documentación: https://docs.github.com/actions
- GitHub Actions — secretos cifrados: https://docs.github.com/actions/security-guides/using-secrets-in-github-actions
- pytest — documentación: https://docs.pytest.org/
- `unittest.mock` — patching en tests: https://docs.python.org/3/library/unittest.mock.html

**Despliegue en cloud**

- Render — despliegue de servicios y redes privadas: https://render.com/docs
- Railway — documentación: https://docs.railway.com/
- Fly.io — documentación: https://fly.io/docs/
- Kubernetes — conceptos (para saber cuándo NO usarlo): https://kubernetes.io/docs/concepts/

**Datastores**

- PostgreSQL — imagen oficial: https://hub.docker.com/_/postgres
- pgvector: https://github.com/pgvector/pgvector
- Qdrant — documentación: https://qdrant.tech/documentation/

**Repositorios del programa**

- Repositorio oficial de soluciones: https://github.com/LIDR-academy/ai-engineering
- Sesión anterior (base de partida, sistema multi-agente): https://github.com/LIDR-academy/ai-engineering/tree/main/ai-service/exercises
