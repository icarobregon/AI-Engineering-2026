# Estimador CAG

API REST de estimación de proyectos de software usando el patrón **Cache Augmented Generation (CAG)**. El modelo recibe ejemplos reales de estimaciones inyectados en el system prompt para calibrar su salida sin necesidad de fine-tuning.

## Requisitos

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

## Instalación

```bash
cd session_02_fundamentos-de-arquitectura-cag/estimador-cag
uv sync
cp .env.example .env
# Edita .env y añade tus API keys
```

## Arrancar la API

```bash
uv run uvicorn app.main:app --reload
```

La API quedará disponible en `http://localhost:8000`.
Documentación interactiva: `http://localhost:8000/docs`

## Ejemplo de uso

```bash
curl -X POST http://localhost:8000/api/v1/estimate \
  -H "Content-Type: application/json" \
  -d '{"transcription": "El cliente necesita una landing page con formulario de contacto, integración con HubSpot, y blog con editor WYSIWYG. Plazo 4 semanas. Diseño ya existe en Figma."}'
```

## Tests

```bash
uv run pytest -v
```

## Variables de entorno

| Variable            | Descripción                                                                           | Por defecto   |
| ------------------- | ------------------------------------------------------------------------------------- | ------------- |
| `APP_ENV`           | `local` o `development` o `staging` o `production`                                    | `local`       |
| `LOG_LEVEL`         | `notset` o `debug` o `info` o `warning` o `warn` o `error` o `exception` o `critical` | `debug`       |
| `LLM_PROVIDER`      | `openai` o `anthropic`                                                                | `openai`      |
| `LLM_MODEL`         | `gpt-4o-mini` o `claude-haiku-4-5`                                                    | `gpt-4o-mini` |
| `OPENAI_API_KEY`    | API key de OpenAI                                                                     | —             |
| `ANTHROPIC_API_KEY` | API key de Anthropic                                                                  | —             |
