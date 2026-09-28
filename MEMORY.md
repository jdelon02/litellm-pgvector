---
type: "project-instructions"
title: "MEMORY.md"
description: "Project instructions source for litellm-pgvector: MEMORY.md."
tags: ["litellm-pgvector", "project"]
source_path: "MEMORY.md"
---

# MEMORY.md

<memory project="litellm-pgvector" format="hybrid-xml-markdown">
  <purpose>
    Durable facts and decisions that future agents should carry forward across
    work sessions in this repository.
  </purpose>
</memory>

## Project Facts

<facts>

- Project ID: `litellm-pgvector`.
- Kind: FastAPI service — OpenAI-compatible Vector Stores API over Postgres/PGVector.
- Embeddings are generated via a LiteLLM proxy (`EMBEDDING__BASE_URL`, default `http://localhost:4000`); the service hosts no models itself.
- Default service port: 8000; auth via `SERVER_API_KEY` bearer token.
- Tables: `vector_stores` and `embeddings` (embedding column `vector(1536)` by default), managed by Prisma.
- Related projects: `dailymodelcheck` (LiteLLM config management), the IMS/context-rag stack (consumer), `scriptwriting`/`delongpa` (project-scoped content ingested here).

</facts>

## Tooling State

<tooling>

- `.codegraph/` exists — use `codegraph_explore` / `codegraph explore` first for code questions; run `codegraph sync` after commits. Initialized 2026-09-28.
- `.code-review-graph/` exists — use its MCP tools for impact analysis; run `code-review-graph update` after commits.
- okf bundle at `docs/knowledge/` (`okf_version: 0.2`, plans/ + specs/); `okf index docs/knowledge/` refreshes, `okf validate docs/knowledge/` checks schema.
- `.githooks/pre-commit` (hooksPath `.githooks`): updates code-review-graph, lints `docs/knowledge` when `docs/` changes are staged, and runs the RAG ingestion step.

</tooling>

## Durable Decisions

<decisions>

- OpenAI Vector Stores compatibility is contract; extensions must be additive and optional.
- Project scoping via `metadata.project_id`: top-level `project_id`, `filters.project_id`, or in-query markers (`project_id: x`, `project: x`, `project ID=x`). Conflicts, blank values, and marker-only queries are 422 before DB/embedding calls.
- Records with missing/null `metadata.project_id` do not match a scoped search.
- Project filtering is explicitly not authorization.
- Contract tests are hermetic: no generated Prisma client, no live DB or proxy; run with `LITELLM_LOCAL_MODEL_COST_MAP=True`.
- Database field names are configurable via `DB_FIELDS__*`; code must go through this mapping, not hard-coded column names.
- No database schema change was needed for project scoping — it lives in JSON metadata.

</decisions>

## Secrets And External State

<secrets>

- `.env` holds `DATABASE_URL`, `SERVER_API_KEY`, and `EMBEDDING__API_KEY`; it is untracked and must stay that way.
- The LiteLLM proxy and Postgres are external services; this repo assumes they exist but never manages their credentials beyond `.env`.

</secrets>

## Agent Reminders

<agent_reminders>

- A contract change is complete only when `models.py`, `main.py`, `README.md`, and `tests/` all agree.
- `search_query` in responses is the marker-cleaned query; keep that behavior when touching marker parsing.
- Keep `/v1/` and legacy unprefixed routes in behavioral lockstep.
- After substantive commits: `codegraph sync && code-review-graph update`; after bundle doc changes: `okf index docs/knowledge/`.
- HTTPX stays pinned to the version in `requirements-dev.txt` until FastAPI/Starlette are upgraded together.

</agent_reminders>
