# business-backend

El punto de entrada público del sistema de estimación: interfaz y BFF en la misma
pieza. Next.js 16 (App Router) + React 19 + Ant Design 6 + Prisma sobre Postgres.

Sustituye a la aplicación Ruby on Rails de la implementación de referencia. El
reparto de responsabilidades es el mismo: **aquí no se estima nada**. Esta capa
valida entrada, llama al servicio IA, traduce sus errores a algo accionable,
persiste el histórico y pinta el resultado. La lógica de dominio vive en Python.

## Cómo se ejecuta

Con el resto del sistema, desde la raíz de la carpeta de la sesión:

```bash
docker compose up
```

Ver [`../docs/deployment-local.md`](../docs/deployment-local.md) para el arranque
completo y las cinco comprobaciones.

## Estructura

```
src/
├── app/                      # rutas (App Router)
│   ├── page.tsx              # panel
│   ├── estimations/          # S04 — estimación transaccional
│   ├── chat/                 # S05 — conversación con memoria, y modo Actor-Critic-Boss
│   ├── lab/chunking/         # S07 — comparador de estrategias de troceado
│   ├── supervisor/           # S14 — supervisor, traza de enrutado y bandeja de revisión
│   ├── ajustes/              # modelos en caliente (PUT /api/v1/config/models)
│   └── api/health/           # liveness del propio contenedor
├── lib/
│   ├── estimator/            # FOUNDATION — lo único que habla HTTP con el servicio IA
│   │   ├── client.ts         #   fetch + timeouts + taxonomía de errores
│   │   ├── contracts.ts      #   espejo en zod de los schemas Pydantic
│   │   ├── errors.ts         #   EstimatorError y sus seis clases
│   │   ├── estimations.ts    #   POST /api/v1/estimate
│   │   ├── sessions.ts       #   POST /sessions (+ /estimate, /estimate/acb)
│   │   ├── chunking.ts       #   POST /chunking/compare (+ /search)
│   │   ├── graph.ts          #   POST /v1/estimate/graph (+ resume)
│   │   └── config.ts         #   GET/PUT /api/v1/config/models
│   ├── data/                 # presupuestos de muestra que alimentan el laboratorio
│   ├── db.ts                 # cliente Prisma
│   └── supervisor.ts         # mapeo respuesta → fila, compartido por start y resume
└── components/
```

## Decisiones de diseño

**Una sola puerta al servicio IA.** Todo lo que cruza la frontera pasa por
`lib/estimator/`, y esos módulos empiezan con `import "server-only"`. Importarlos
desde un componente de cliente es un error de compilación, así que el secreto de
servicio no puede acabar en un bundle del navegador ni por descuido.

**Contratos parseados, no casteados.** El servicio IA devuelve el estimate como
un `dict` sin tipar. Validarlo con zod al leerlo convierte un cambio silencioso
de contrato en un mensaje claro en pantalla, en vez de una página en blanco tres
componentes más abajo.

**Errores como taxonomía, no como códigos.** `EstimatorError` distingue seis
casos (guardrail, petición inválida, no autorizado, no encontrado, rate limit, no
disponible, error del servidor) porque cada uno pide una reacción distinta de la
interfaz. Un 400 de guardrail se le enseña al usuario tal cual; un 503 no.

**Un único mapeo de respuesta a fila** (`lib/supervisor.ts`), usado por el
arranque y por la reanudación, para que la forma persistida no pueda desviarse
del contrato. Los `?? current` no son ruido defensivo: las ramas idempotentes del
router de Python contestan sin `review_payload`, así que un mapeo que
sobrescribiera a ciegas borraría el informe del revisor en cuanto alguien
recargara la página.

**La decisión humana se guarda aquí.** Quién aprobó qué, cuándo y por qué es
historia de negocio. El servicio IA sabe pausar y reanudar; la autorización y el
registro son de esta capa.

**Esquema de Postgres aparte.** Misma base de datos que el servicio IA,
`?schema=business` en la cadena de conexión: un datastore que operar y cero
posibilidad de colisión de tablas.

## Limitaciones conocidas

- **Sin usuarios ni permisos.** Igual que la implementación de referencia. Toda la
  autorización que existe es el token entre servicios. Añadir login es alcance
  nuevo, no paridad.
- **La cabecera es `X-API-Key`, no `X-Service-Token`.** Mismo mecanismo, otro
  nombre; renombrarla obliga a tocar el servicio IA, sus tests y su documentación.
- **Sin tests.** El BFF no tiene batería propia todavía.
- **Pantallas no portadas:** asistente RAG de cinco pasos (S09–S12), corpus e
  índice (S11), consola de agentes (S12) y el asistente de grafo con feed en
  vivo y PDF (S13). Las tres últimas exigirían además endpoints nuevos en el
  servicio IA.
- **Desarrollo fuera de Docker.** Con la frontera cerrada, `localhost:8000` y
  `localhost:5433` ya no existen; iterar sin contenedores exige publicarlos
  temporalmente.
