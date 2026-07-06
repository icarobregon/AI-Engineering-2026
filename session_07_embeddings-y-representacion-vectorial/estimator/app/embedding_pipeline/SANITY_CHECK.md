# SANITY_CHECK — pipeline de embeddings

Comprobación mínima de que el pipeline funciona de extremo a extremo, no una
validación formal de calidad de retrieval. Modelo: `text-embedding-3-small`
(1536 dims). Métrica: similitud coseno calculada a mano en `scripts/compare.py`.

Los tres pares son textos fijos del enunciado, independientes del dataset de
presupuestos; sirven para confirmar que el embedder discrimina contenido cercano
de contenido lejano.

Reproducir:

```bash
uv run python scripts/compare.py --text-a "<A>" --text-b "<B>"
```

## Resultados

| Par | Texto A | Texto B | Similitud | Expectativa |
|-----|---------|---------|-----------|-------------|
| A | OAuth 2.0 authentication backend with JWT tokens for fintech mobile app | Authorization service using JSON Web Tokens for a banking application | **0.5957** | >0.6 (orientativo) |
| B | OAuth 2.0 authentication backend with JWT tokens for fintech mobile app | Database migration from MySQL to PostgreSQL with zero downtime | **0.1920** | <0.4 (orientativo) |
| C | Backend services | API development | **0.5408** | sin expectativa fija |

## Comentario

El resultado coincide con la intuición en lo esencial: el par B (dos tareas de
dominios distintos, autenticación vs migración de base de datos) queda muy bajo
(0.19), y el par A —dos formas de describir lo mismo con vocabulario diferente
("OAuth 2.0 authentication"/"Authorization service", "JWT"/"JSON Web Tokens")—
queda claramente por encima. Lo que llama la atención es que A se queda en 0.596,
apenas por debajo del 0.6 orientativo: los umbrales son eso, orientativos, y hay
que calibrarlos sobre el propio dataset (la "maldición de la dimensionalidad" que
menciona el material). Más revelador aún es el par C: dos términos genéricos y
cortos ("Backend services"/"API development") puntúan 0.54, casi tanto como A;
los textos vagos y sin contexto tienden a agrupar alto entre sí, lo que refuerza
por qué el chunker antepone un header de contexto del presupuesto padre a cada
componente en lugar de embeber texto pelado.
