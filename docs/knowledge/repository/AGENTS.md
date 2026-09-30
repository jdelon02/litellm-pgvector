---
type: "project-instructions"
title: "Agent Instructions for litellm-pgvector"
description: "Project instructions source for litellm-pgvector: AGENTS.md."
tags: ["litellm-pgvector", "project"]
source_path: "AGENTS.md"
---

# Agent Instructions for litellm-pgvector

<entry_point>
  This repository utilizes a modular 5-tier context stack. Before taking any action or processing tasks, load the root context files in order:
  1. SOUL.md - Identity, API-compatibility guardrails, and judgment.
  2. STYLE.md - Python, API, and documentation conventions.
  3. SKILL.md - The repo-native skill: when and how to work here safely.
  4. MEMORY.md - Durable facts, decisions, and invariants.
  5. README.md - User-facing API reference, configuration, and setup.
</entry_point>

<capabilities_and_tools>

  <code_discovery_engines>
    **IMPORTANT: ALWAYS use CodeGraph or code-review-graph BEFORE Grep/Glob/Read to explore the codebase.**
    The graphs are faster, cheaper (fewer tokens), and provide structural context (callers, dependents, request-flow paths, test coverage) that file scanning cannot. Fall back to Grep/Glob/Read **only** when the graphs do not cover what you need.

    <tool_selection_strategy>
      - **Macro Scope & Risk Analysis:** Reach for `code-review-graph` first to evaluate change blast radius (e.g. a change to `config.py` field mappings or `models.py` request shapes), review architectural layout, or score diff risk.
      - **Micro Navigation & Dynamic Hops:** Reach for `CodeGraph` (`codegraph_explore`) to trace specific endpoints in `main.py`, embedding calls in `embedding_service.py`, or validation paths through `models.py`.
    </tool_selection_strategy>

    <!-- CODEGRAPH_START -->
    ## CodeGraph

    In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

    - **MCP tool** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim source plus the call paths between them, including dynamic-dispatch hops grep can't follow. Name a file or symbol in the query to read its current line-numbered source.
    - **Shell** (always works): `codegraph explore "<symbol names or question>"` prints the same output.
    - **Maintenance**: after substantive commits, run `codegraph sync` to keep the index current.

    If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.
    <!-- CODEGRAPH_END -->

    <!-- code-review-graph MCP tools -->
    ## code-review-graph Matrix
    In repositories indexed by code-review-graph (a `.code-review-graph/` directory exists at root):

    | Tool | Use when |
    | :--- | :--- |
    | `detect_changes_tool` | Reviewing code changes — gives risk-scored analysis |
    | `get_review_context_tool` | Need source snippets for review — token-efficient |
    | `get_impact_radius_tool` | Understanding blast radius of a change before modifying code |
    | `get_affected_flows_tool` | Finding which endpoints or request paths are impacted |
    | `query_graph_tool` | Tracing callers, callees, imports, and dependencies |
    | `semantic_search_nodes_tool` | Finding functions/classes by name or keyword |
    | `get_architecture_overview_tool` | Understanding high-level codebase structure |
    | `refactor_tool` | Planning renames, finding dead code |

    Keep the graph fresh with `code-review-graph update` after committing changes.
    <!-- code-review-graph END -->
  </code_discovery_engines>

  <knowledge_engine tool="okf">
    - **Knowledge Bundle Location:** `docs/knowledge/`
    - **Discovery Rule:** Use the `okf` CLI (`okf search`, `okf show`, `okf backlinks`) to discover plans and specs before reading raw documentation files.
    - **Validation Rule:** Run `okf validate docs/knowledge/` after modifying documentation or specs to ensure schema compliance before committing. The `.githooks/pre-commit` hook lints `docs/knowledge` automatically when `docs/` changes are staged.
    - **Reindex Rule:** Run `okf index docs/knowledge/` after adding or restructuring bundle documents.
  </knowledge_engine>

</capabilities_and_tools>

<agentic_instructions project="litellm-pgvector" format="hybrid-xml-markdown">
  <purpose>
    litellm-pgvector is a FastAPI service exposing OpenAI-compatible Vector
    Stores endpoints backed by Postgres/PGVector, with embeddings generated
    through a LiteLLM proxy. It is the vector-store backend for the IMS/RAG
    ecosystem (project-scoped retrieval via metadata.project_id).
  </purpose>

  <instruction_files>
    - Read `SOUL.md` for project identity and judgment.
    - Read `SKILL.md` for the reusable repo-work skill.
    - Read `STYLE.md` for code and documentation style.
    - Read `MEMORY.md` for durable facts, decisions, and invariants.
    - Treat this `AGENTS.md` as the operational command center.
  </instruction_files>
</agentic_instructions>

## Project Overview

<repo_map>

### Source

- `main.py`: FastAPI app — all `/v1/vector_stores*` routes (create/list stores, single/batch embedding insert, search), auth, project_id handling, query-marker parsing.
- `models.py`: Pydantic request/response models (OpenAI-compatible shapes, project_id validation rules).
- `embedding_service.py`: embedding generation through the LiteLLM proxy.
- `config.py`: pydantic-settings configuration — `DATABASE_URL`, `SERVER_API_KEY`, `EMBEDDING__*`, `DB_FIELDS__*` (nested via `__` delimiter, `.env` supported).
- `prisma/`: Prisma schema for `vector_stores` and `embeddings` tables.
- `tests/`: unittest-based contract tests (HTTP routes + validation; DB and embedding calls are isolated).

### Docs and Tooling

- `README.md`: full API reference, configuration, migration guide.
- `docs/knowledge/`: okf bundle (plans, specs).
- `.githooks/pre-commit`: runs code-review-graph update, okf lint on staged `docs/` changes, and the RAG ingestion step.

</repo_map>

## Non-Negotiable Rules

<rules priority="highest">

- Preserve OpenAI Vector Stores API compatibility: request/response shapes, `object` values, and error semantics are contract. Additions must be backwards-compatible.
- Preserve the project-scoping contract: `project_id` (top-level, `filters.project_id`, or in-query markers) with its documented 422 conflict/blank rules. Optional project filtering is not authorization.
- Never commit secrets. `.env` holds `DATABASE_URL`, `SERVER_API_KEY`, and `EMBEDDING__API_KEY`; it stays untracked.
- Working in a worktree or fresh clone: copy `.env` from the primary checkout (currently `/Users/jdelon02/Projects/agentic_related/litellm-pgvector/.env`) into the working directory before committing. The pre-commit RAG step (`scripts/push_to_rag.py --hook`) needs `rag_base_url`, `rag_api_key`, `NANOGPT_API_KEY`, and `PROJECT_ID`; without them the hook blocks every commit. `PROJECT_ID` is the content boundary — it stamps `metadata.project_id` on ingested chunks and is the vector store name (created if missing on commit).
- Keep tests hermetic: contract tests must not require a generated Prisma client or live DB/LiteLLM services.
- Do not change database field semantics without going through `DB_FIELDS__*` config and updating README + tests together.
- Schema changes go through `prisma/` and `prisma db push`/migrations, never ad hoc SQL in code.
- If `.codegraph/` exists, use CodeGraph before grep/find/read when locating or understanding code.
- Run `okf validate docs/knowledge/` before committing documentation/spec changes.

</rules>

## Common Commands

<commands>

### Run

```bash
pip install -r requirements.txt
prisma generate && prisma db push
python main.py                      # or: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Tests

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
LITELLM_LOCAL_MODEL_COST_MAP=True python -m unittest discover -s tests -v
```

### Graph maintenance

```bash
codegraph sync && code-review-graph update
```

### Knowledge bundle

```bash
okf search "<concept>"
okf validate docs/knowledge/
okf index docs/knowledge/
```

### Docker

```bash
docker build -t vector-store-api .
docker run -p 8000:8000 --env-file .env vector-store-api
```

</commands>

## Debugging Guide

<debugging>

- 401s: check `SERVER_API_KEY` and the `Authorization: Bearer` header; embedding 401s are the LiteLLM proxy's `EMBEDDING__API_KEY` instead.
- Empty search results with a `project_id`: records whose `metadata.project_id` is missing or null never match a specified project — verify ingestion stamped the metadata.
- 422 on search: check for conflicting `project_id` locations, blank identifiers, or malformed/marker-only queries per README rules.
- Wrong embedding dimensions: `EMBEDDING__DIMENSIONS` must match the `vector(N)` column in the Prisma schema.
- If graph queries miss recent edits, run `codegraph sync` and `code-review-graph update`.
- If okf results look stale, re-run `okf index docs/knowledge/`.

</debugging>
