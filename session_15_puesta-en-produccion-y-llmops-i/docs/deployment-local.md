# Arranque local del sistema completo

Cuatro contenedores, un comando, y una única puerta al exterior.

## Requisitos

- Docker y Docker Compose (`docker --version`, `docker compose version`).
- Una clave del proveedor de LLM.

## Puesta en marcha

```bash
cd session_15_puesta-en-produccion-y-llmops-i

cp .env.example .env                        # secreto de servicio + credenciales de Postgres
cp estimator/.env.example estimator/.env    # claves del proveedor de LLM y ajustes del servicio IA
```

Rellena ahora `.env`, **antes de construir**: el arranque aborta con
`required variable AI_SERVICE_TOKEN is missing a value` si lo dejas vacío, que es
el comportamiento buscado —fallar ruidosamente en vez de servir con un secreto en
blanco— pero conviene saberlo antes de toparse con él.

| Variable | Qué es |
| --- | --- |
| `AI_SERVICE_TOKEN` | El secreto compartido entre el backend de negocio y el servicio IA. Un valor por entorno. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Credenciales del datastore. Se interpolan en las cadenas de conexión de ambos servicios, así que no hay ninguna contraseña escrita en `docker-compose.yml`. |

Y en `estimator/.env`, al menos `OPENAI_API_KEY` o `ANTHROPIC_API_KEY`. Con una
sola se arranca, pero el catálogo de modelos de la pantalla «Ajustes» se queda con
la mitad: son 27 modelos de OpenAI y 11 de Anthropic, y el endpoint sólo ofrece
los del proveedor cuya clave esté puesta. Y si falta la de Anthropic, el modelo de
respaldo por defecto —`claude-haiku-4-5-20251001`— no es alcanzable.

```bash
docker compose build
docker compose up
```

**Arranca siempre desde este directorio.** Compose deriva el nombre del proyecto
—y con él los nombres de los volúmenes— del sitio desde el que se lanza. Hacerlo
desde una subcarpeta crearía un segundo corpus vacío sin avisar.

## Las cinco comprobaciones

Una ejecución real de las cinco, con su salida, está capturada en
[`evidencia-cinco-comprobaciones.txt`](evidencia-cinco-comprobaciones.txt). Lo que
sigue es cómo reproducirla.

### 1. Los cuatro servicios arriba y sanos

```bash
docker compose ps
```

Los cuatro —`business-backend`, `ai-service`, `estimator-postgres` y `redis`—
deben aparecer en estado `healthy`; los cuatro llevan healthcheck. Además verás
`business-migrate` en `Exited (0)`: es el contenedor de un solo uso que aplica el
esquema de Prisma y termina antes de que arranque la aplicación.

### 2. El backend de negocio sirve desde el host

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:3000
```

Debe responder `200`. En el navegador, http://localhost:3000 muestra el panel, y
desde ahí se llega a las cinco pantallas: Estimación (`/estimations`),
Conversación (`/chat`), Supervisor (`/supervisor`), Laboratorio (`/lab/chunking`)
y Ajustes (`/ajustes`). Las cinco deben devolver `200`:

```bash
for r in / /estimations /chat /supervisor /lab/chunking /ajustes; do
  printf '%-16s %s\n' "$r" "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:3000$r)"
done
```

### 3. El servicio IA NO es alcanzable desde el host

```bash
curl -sS -m 3 http://localhost:8000/health || echo "OK: el servicio IA no es alcanzable desde el host"
```

Debe fallar la conexión. Es la comprobación más importante del entregable: el
servicio IA custodia la clave del LLM y por debajo de él viven las reglas de
negocio, así que publicar su puerto sería regalar la factura y permitir
saltarse la capa que decide quién puede pedir una estimación.

Desde dentro de la red sí responde:

```bash
docker compose exec business-backend node -e "fetch('http://ai-service:8000/health').then(r=>r.json()).then(console.log)"
```

### 4. Una estimación recorre el flujo completo

En http://localhost:3000/supervisor/new, pega una transcripción y lanza la
estimación. El recorrido es: navegador → backend de negocio → servicio IA (con
el token) → Postgres/pgvector → respuesta. Si la confianza es baja, la ejecución
se detiene y aparece en la bandeja de revisión.

Las rutas que **estiman** exigen el token de servicio: `/api/v1/estimate` (pantalla
«Estimación») y las tres del grafo —`/v1/estimate/graph`, su `resume` y su
`state`— que sirven a la del supervisor. Sin cabecera, 401 en ambos caminos:

```bash
docker compose exec business-backend node -e "
const body = JSON.stringify({transcript:'x'});
for (const url of ['http://ai-service:8000/api/v1/estimate','http://ai-service:8000/v1/estimate/graph']) {
  fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body}).then(r=>console.log(url, r.status));
}"
```

**Y las tres familias que servían a las pantallas nuevas también.** Sesiones
(`/sessions/*`, «Conversación»), troceado (`/embeddings/*`, el laboratorio) y
configuración (`/api/v1/config/*`, «Ajustes») dejaron de ser anónimas: son dos
barreras, no una. La red mantiene el servicio inalcanzable desde fuera, y la clave
lo mantiene inutilizable por cualquier otra cosa que acabe corriendo dentro.
Comprobación, desde la propia red:

```bash
docker compose exec -T ai-service python -c "
import urllib.request, urllib.error
rutas = [('POST','/sessions'),('POST','/embeddings/compare'),('GET','/api/v1/config/models'),
         ('POST','/search'),('POST','/api/v1/ingestion/runs'),('GET','/health')]
for metodo, ruta in rutas:
    req = urllib.request.Request('http://localhost:8000'+ruta, method=metodo,
                                 data=b'{}' if metodo=='POST' else None,
                                 headers={'Content-Type':'application/json'})
    try: code = urllib.request.urlopen(req).status
    except urllib.error.HTTPError as e: code = e.code
    print(f'{metodo:5} {ruta:26} -> {code}')
"
```

Debe dar `401` en las cinco primeras y `200` en `/health`, que es **lo único que
queda abierto**, y a propósito: cerrarlo mataría el healthcheck de Docker y con él
el arranque ordenado de compose.

### 5. Los datos sobreviven a un ciclo completo

```bash
docker compose down && docker compose up -d
```

El corpus y el histórico siguen ahí: ambos viven en volúmenes con nombre
(`postgres_data`, `redis_data`). Ojo: `docker compose down -v` sí los borra.

Lo mismo vale para los cambios de modelo hechos en «Ajustes»: viven en el hash de
Redis `estimator:runtime_config`, no en `.env`, así que sobreviven al ciclo. Es la
comprobación que distingue un override de un reinicio: si tras `down && up` la
pantalla sigue marcando «override», la persistencia funciona.

## Sembrar el corpus

Un sistema recién levantado arranca, pasa el healthcheck **y no estima**: sin
corpus vectorial cada componente vuelve sin precedente, con confianza 0.0, y toda
ejecución acaba en la bandeja de revisión. Verde por fuera, inútil por dentro.

**Hay dos corpus y no son intercambiables.** Es el error que más caro sale aquí,
porque sembrar el equivocado no da ningún fallo: el sistema responde, la traza se
ve entera y todos los componentes salen «sin precedente», que es exactamente lo
que se vería si el corpus estuviese vacío.

| Corpus | Granularidad | `chunk_type` | Lo consume |
| --- | --- | --- | --- |
| `budgets_sample.json` | un chunk por componente de presupuesto | `budget_component` | el retrieval directo de la S08–S11 |
| `task_corpus.json` | un chunk por tarea histórica | `historical_task` | **el agente y el supervisor** (S12–S14) |

El backend de `search_budgets` filtra por `chunk_type='historical_task'`
(`app/dependencies.py`, `get_budget_search_backend`), así que el camino agéntico
—el que atraviesa la interfaz— necesita el segundo:

```bash
# el que necesita el supervisor: corpus a nivel de tarea
docker compose exec ai-service python scripts/build_task_corpus.py --ingest

# opcional, para el retrieval directo de sesiones anteriores
docker compose exec ai-service python scripts/query_examples.py
```

Ambos son idempotentes: lo ya ingerido devuelve 409 y se salta. Para comprobar
que el corpus que hace falta está puesto:

```bash
docker compose exec -T estimator-postgres psql -U estimator -d estimator \
  -tAc "select chunk_type, count(*) from public.budget_chunks group by chunk_type"
```

Si `historical_task` no aparece, la interfaz estimará sin evidencia.

## Desviaciones respecto al enunciado

Conscientes, y aquí para que quien revise no las tome por errores.

| El enunciado dice | Aquí es | Por qué |
| --- | --- | --- |
| carpeta `ai-service/` | carpeta `estimator/` | Es el nombre que el proyecto arrastra desde la Sesión 2; renombrarlo rompería las referencias de trece sesiones. El **servicio** de compose sí se llama `ai-service`, que es lo que fija el criterio de aceptación: el backend de negocio lo alcanza por `http://ai-service:8000`. |
| cabecera `X-Service-Token` | cabecera `X-API-Key` | Mismo mecanismo —un secreto compartido por entorno, exigido en las rutas de estimación y ausente en `/health`—. Renombrarla obliga a tocar el servicio IA, sus tests y su documentación. |
| contrato en `/v1/estimate` | `/v1/estimate/graph`, `/v1/estimate/from-transcript`, `/v1/estimate/stages/*`, `/v1/estimate/tasks/*` | `/v1/estimate` a secas devuelve 404: es un prefijo, no una ruta. La pantalla del supervisor usa `/v1/estimate/graph`. |
| cuatro servicios, con BBDD vectorial aparte | tres contenedores de datos + la app | pgvector hace de relacional y de vectorial en el mismo contenedor, que el propio enunciado autoriza. El cuarto es Redis Stack, que sostiene la caché semántica de sesiones anteriores. |
| — | `business-migrate` | Contenedor de un solo uso que aplica el esquema de Prisma y sale con 0. No es un servicio permanente; mantener el CLI de Prisma en la imagen de runtime costaba 250 MB. |

## Ejecutar el servicio IA fuera de Docker

Esto es otra cosa que lo de arriba: no levantar el sistema, sino correr
`uvicorn` en la máquina contra las dependencias del Compose. Sirve para depurar
con el depurador puesto, para iterar sin reconstruir la imagen y para lanzar los
scripts de `scripts/` a mano.

**Hoy no funciona.** La arquitectura la contempla —`docker-compose.yml`
sobrescribe `REDIS_URL` y `DATABASE_URL` con el comentario «these override
whatever the .env says: those values are written for running uvicorn outside
Docker»— pero hay dos cosas rotas y una que faltaba.

### Qué lo bloquea

**1. Los datastores no publican puerto.** Desde la S15 sólo `business-backend`
publica el 3000; Postgres y Redis se hicieron privados a propósito. Comprobado:
los puertos 5433 y 6379 están cerrados en el host. Sin ellos, uvicorn en la
máquina no alcanza ni la base ni la caché. Es el obstáculo real, y es
consecuencia de una decisión deliberada, no de un descuido.

**2. El `.env` había derivado a una topología mezclada.** `DATABASE_URL`
apuntaba a `localhost:5433` (valor de host, correcto según la intención) pero
`REDIS_URL` a `redis://redis:6379` (valor de contenedor). Con esa mezcla, ni la
vía local ni nada: media configuración miraba a un sitio y media al otro.
Corregido — las dos líneas del `.env` son ahora de host, y Compose sigue
sobrescribiéndolas para el contenedor, que era el reparto previsto.

**3. `DATABASE_URL` y `REDIS_URL` ya no tienen valor por defecto.** Antes lo
tenían, y apuntaba a `localhost:5433` / `localhost:6379` — es decir, el default
del código ERA la vía local, y por eso la deriva no se notaba: arrancabas fuera
de Docker y «funcionaba» aunque el `.env` dijera otra cosa. Ahora hay que
declararlas. Es más trabajo de configuración y menos sorpresas.

### Qué haría falta

Lo mínimo son dos líneas en `docker-compose.yml`, publicando **sólo en el
loopback**:

```yaml
  estimator-postgres:
    ports:
      - "127.0.0.1:5433:5432"

  redis:
    ports:
      - "127.0.0.1:6379:6379"
```

El `127.0.0.1:` no es un detalle: sin él, `"5433:5432"` escucha en todas las
interfaces y el contenedor queda alcanzable desde la red local. Con él, la
frontera de la S15 se mantiene —el sistema sigue teniendo una sola puerta
pública, el 3000— y lo único que cambia es que la propia máquina puede hablar
con sus datastores.

Con eso, el flujo es:

```bash
# sólo las dependencias, no el servicio IA
docker compose up -d estimator-postgres redis

cd estimator
uv run uvicorn app.main:app --reload    # lee estimator/.env, que ya es de host
```

Las migraciones y el corpus ya están en el volumen, así que no hay que sembrar
nada: es la misma base que usa el contenedor.

### Qué cuesta mantenerla

Poco, pero no cero:

- **Dos líneas de `ports`**, y recordar el `127.0.0.1:`.
- **La disciplina del reparto**: el `.env` lleva valores de HOST y Compose los
  sobrescribe para el contenedor. Ya está así y documentado en los dos ficheros;
  lo que hay que evitar es «arreglar» el `.env` poniéndole nombres de servicio,
  que es exactamente la deriva que se corrigió aquí.
- **Nada más.** No hay que duplicar ficheros de entorno ni mantener un perfil de
  Compose aparte.

### Qué NO da esta vía

**El sistema mixto no funciona.** Si el servicio IA corre en el host, el BFF
dentro de Docker no lo alcanza: su `AI_SERVICE_URL` es `http://ai-service:8000`,
un nombre que sólo existe en la red de Compose. Haría falta apuntarlo a
`http://host.docker.internal:8000`, que es otra configuración y otro conjunto de
suposiciones. La vía local es para el **servicio IA aislado** —tests, scripts,
depuración—, no para levantar medio sistema fuera y medio dentro.

### Alternativa, si no se quieren publicar puertos

`docker compose exec ai-service python …` para lo puntual, o un contenedor
efímero enganchado a la red (`docker run --rm --network <red> …`). Funciona y no
toca la frontera, pero es más ceremonia que dos líneas de `ports` y no da
depurador.

**Recomendación**: publicar en loopback. Es reversible, explícito, y no
contradice la decisión de la S15 — la frontera es que el servicio IA y sus
datastores no estén expuestos *a la red*, y en loopback siguen sin estarlo.

## Qué NO está aquí


- **Desarrollo del front fuera de Docker.** Cerrar la frontera significa que
  `localhost:8000` y `localhost:5433` ya no existen. Para iterar sobre la UI sin
  contenedores hay que publicar temporalmente esos puertos, a sabiendas.
