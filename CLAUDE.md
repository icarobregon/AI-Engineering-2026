# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository purpose

Personal coursework for the **AI Engineering 2026/05** master's program by [LIDR.co](https://www.lidr.co/ai-engineering/). The repo collects exercises and a single evolving project across 18 sessions (0–17): an automated software-estimation system that consumes meeting transcripts and produces budgets from company history. Each session adds a new architectural layer on top of the previous one (LLM wrappers → CAG → RAG → agents → LLMOps).

`main` is intentionally minimal — README, LICENSE, `.gitignore`, this file. Real code lives on per-session branches.

## Branching and folder layout

One branch per session, one top-level folder per session inside that branch:

```
session_00_welcome-session/
session_01_llms-y-setup-de-entorno-de-trabajo/
session_02_fundamentos-de-arquitectura-cag/
...
session_17_laboratorio-10x-engineer/
```

When starting work for a new session, branch from `main` and create the matching `session_NN_<kebab-slug>/` directory at the repo root. Keep changes scoped to that folder — do not touch other sessions' directories from a session branch. At the end of the program all session branches will be merged back to `main`.

When asked to work on "session N", first check whether a `session_NN_*` branch already exists locally or on `origin` before creating a new one.

## Tech stack (used across sessions as introduced)

- **Python** with **FastAPI** (backend) and **Streamlit** (UI)
- **Docker** for local environments, Google Colab for quick experimentation
- LLM providers: **OpenAI** (GPT-4o, o1), **Anthropic** (Claude), **Google** (Gemini) — via their official SDKs
- Architectures introduced in order: plain LLM calls → CAG (Cache Augmented Generation) → RAG → agents / multi-agent → LLMOps

Each session folder is expected to be self-contained with its own `README.md` (setup, design decisions, limitations) and its own dependency manifest (`requirements.txt` / `pyproject.toml` / `Dockerfile`) — there is no shared root-level Python environment. Run commands (install, test, serve) live inside each session folder; consult that folder's README before assuming a command works.

## Repository policy (enforced by program guidelines)

From the [LIDR Política de Gestión de Repositorios](https://training.lidr.co/posts/ai-engineering-202605-%F0%9F%93%9C-politica-de-gestion-de-repositorios):

- Never commit `.env` files. Provide `.env.example` listing required variable names with placeholder values.
- Never commit API keys, tokens, or credentials in any file, including notebooks and example data.
- Never commit real user data or PII. Sample data must be fictitious or anonymized.
- Each exercise should ship with documentation covering setup, design decisions, and known limitations.

## Reference

Official solution repositories (for cross-checking approach, not copying):

- Sessions 00–01: https://github.com/LIDR-academy/ai-engineering-pre-sessions/tree/main/session_01
- Sessions 02+: https://github.com/LIDR-academy/ai-engineering
