# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

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
