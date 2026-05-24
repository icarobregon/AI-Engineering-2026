# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Context

Personal learning repository for the **LIDR AI Engineering Master's** program — a 17-week course covering the full stack of AI product development: LLM integration, CAG, RAG, agent orchestration, and LLMOps. Sessions run weekly; code, notes, and exercises accumulate over time.

## Repository structure

Each session directory follows this convention:

```
sesion-XX_<topic>/
├── README.md    # session summary and key learnings
├── src/         # code written during the session
└── notes.md     # personal notes and additional resources
```

Top-level directories map to the course modules:
- `sesion-00` to `sesion-01` — Foundations (LLMs, environment setup)
- `sesion-02` to `sesion-05` — CAG (Cache Augmented Generation) architectures
- `sesion-06` to `sesion-08` — Data-driven AI (embeddings, vector DBs)
- `sesion-09` to `sesion-11` — RAG architectures
- `sesion-12` to `sesion-14` — Agent orchestration and multi-agent systems
- `sesion-15` — Production deployment / LLMOps
- `laboratorio_10x-engineer/` — Spec-Driven Dev, Agents, MCPs lab
- `proyecto-final/` — Final capstone project

## Tech stack

- **LLM APIs:** OpenAI, Anthropic (keys in `.env`, never commit)
- **Frameworks:** LangChain, LangGraph
- **Observability:** LangSmith, Logfire
- **UI:** Streamlit
- **Vector databases:** TBD as course progresses

## Environment

API keys are stored in `.env` (git-ignored). Load them with `python-dotenv` or equivalent. No global `requirements.txt` yet — each session's `src/` may have its own dependencies as the course progresses.

## Running code

No build system is established yet. Scripts within `src/` are run directly:

```bash
python sesion-XX_<topic>/src/<script>.py
```

If a session introduces a virtual environment or `requirements.txt`, activate/install before running.
