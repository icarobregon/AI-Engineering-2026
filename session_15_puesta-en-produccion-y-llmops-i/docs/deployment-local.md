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

docker compose build
docker compose up
```

**Arranca siempre desde este directorio.** Compose deriva el nombre del proyecto
—y con él los nombres de los volúmenes— del sitio desde el que se lanza. Hacerlo
desde una subcarpeta crearía un segundo corpus vacío sin avisar.

Rellena en `.env`:

| Variable | Qué es |
| --- | --- |
| `AI_SERVICE_TOKEN` | El secreto compartido entre el backend de negocio y el servicio IA. Un valor por entorno. Sin él, el arranque falla en vez de servir con un secreto vacío. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Credenciales del datastore. Se interpolan en las cadenas de conexión de ambos servicios, así que no hay ninguna contraseña escrita en `docker-compose.yml`. |

## Las cinco comprobaciones

### 1. Los cuatro servicios arriba y sanos

```bash
docker compose ps
```

`business-backend`, `ai-service` y `estimator-postgres` deben aparecer en estado
`healthy`; `redis` en `running`.

### 2. El backend de negocio sirve desde el host

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:3000
```

Debe responder `200`. En el navegador, http://localhost:3000 muestra el panel.

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

Comprobación de que el token se exige de verdad —sin cabecera, 401:

```bash
docker compose exec business-backend node -e "fetch('http://ai-service:8000/v1/estimate/graph',{method:'POST',headers:{'Content-Type':'application/json'},body:'{\"transcript\":\"x\"}'}).then(r=>console.log(r.status))"
```

### 5. Los datos sobreviven a un ciclo completo

```bash
docker compose down && docker compose up -d
```

El corpus y el histórico siguen ahí: ambos viven en volúmenes con nombre
(`postgres_data`, `redis_data`). Ojo: `docker compose down -v` sí los borra.

## Sembrar el corpus

Un sistema recién levantado arranca, pasa el healthcheck **y no estima**: sin
corpus vectorial, cada componente vuelve con `has_match=false` y confianza
`insufficient`. Verde por fuera, inútil por dentro. Se siembra una vez:

```bash
docker compose exec ai-service python scripts/query_examples.py
```

Es idempotente: los presupuestos ya ingeridos devuelven 409 y se saltan.

## Qué NO está aquí

- **Desarrollo del front fuera de Docker.** Cerrar la frontera significa que
  `localhost:8000` y `localhost:5433` ya no existen. Para iterar sobre la UI sin
  contenedores hay que publicar temporalmente esos puertos, a sabiendas.
- **La cabecera se llama `X-API-Key`, no `X-Service-Token`.** El enunciado usa el
  segundo nombre; el mecanismo es el mismo —un secreto compartido por entorno,
  exigido en las rutas de estimación y ausente en `/health`— y renombrarlo
  obligaría a tocar el servicio IA, sus tests y su documentación. Queda anotado
  como desviación consciente.
