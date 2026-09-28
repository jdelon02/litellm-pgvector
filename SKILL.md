---
type: "project-instructions"
title: "litellm-pgvector Repo Skill"
tags: ["litellm-pgvector", "project"]
source_path: "SKILL.md"
name: litellm-pgvector
description: Use when working in the litellm-pgvector repo — changing its OpenAI-compatible vector store endpoints, project-scoped search rules, Prisma schema, embedding service, tests, or its okf knowledge bundle.
---

# litellm-pgvector Skill

<skill name="litellm-pgvector" format="hybrid-xml-markdown">
  <purpose>
    Guide agents through safe, contract-preserving work on the
    litellm-pgvector vector store API.
  </purpose>
</skill>

## When To Use

<triggers>

Use this skill when the task involves:

- Changing endpoints, request/response models, or validation in `main.py` / `models.py`.
- Modifying project-scoped search behavior (`project_id`, filters, query markers).
- Changing embedding generation (`embedding_service.py`) or configuration (`config.py`).
- Editing the Prisma schema or database field mappings.
- Writing or updating the unittest contract suite.
- Updating the okf bundle under `docs/knowledge/` or the root instruction files.

</triggers>

## Required Context

<context_checklist>

1. Read `AGENTS.md` for the command center and repo map.
2. Read `SOUL.md` for compatibility guardrails and boundaries.
3. Read `STYLE.md` before editing code, tests, or docs.
4. Read `MEMORY.md` for durable facts and invariants.
5. For contract questions, the README's documented rules are authoritative.
6. Use the graphs before file scanning: `code-review-graph` for blast radius, `codegraph_explore` (or `codegraph explore "..."`) for endpoint/symbol questions.
7. Use `okf search` / `okf show` against `docs/knowledge/` before re-deriving plan or spec context.

</context_checklist>

## Workflow Map

<workflow>

```bash
# 1. Understand scope
codegraph explore "<endpoint or symbol>"          # or codegraph_explore MCP tool
# code-review-graph: get_impact_radius_tool / get_affected_flows_tool

# 2. Edit code + README + tests together for contract changes

# 3. Validate
LITELLM_LOCAL_MODEL_COST_MAP=True python -m unittest discover -s tests -v
okf validate docs/knowledge/                                 # if docs changed

# 4. Commit (pre-commit hook runs okf lint + graph update + RAG step), then refresh
codegraph sync && code-review-graph update
okf index docs/knowledge/                          # if bundle docs were added/moved
```

</workflow>

## Safety Pattern

<safety_pattern>

- Contract changes are all-or-nothing across `models.py`, `main.py`, `README.md`, and `tests/`.
- Validation must reject bad scoping (422) before any DB or proxy call.
- Never commit `.env` or weaken the hermetic test isolation.
- Schema changes go through `prisma/`; run `prisma db push` locally, never hand-issue DDL from app code.
- Keep both `/v1/` and legacy route variants behaviorally identical.

</safety_pattern>

## Verification

<verification>

Choose the lightest verification that proves the work:

- Doc-only changes: re-read edited sections; `okf validate docs/knowledge/` when the bundle changed.
- Code changes: run the unittest suite (hermetic, no services needed).
- Contract changes: confirm a test exists for each documented rule touched (conflicts, blanks, markers, precedence).
- Schema/config changes: `prisma generate` succeeds and README env examples still match `config.py` defaults.

</verification>

## Common Gotchas

<gotchas>

- `project_id` may arrive three ways (top-level, `filters.project_id`, in-query marker); matching values dedupe, conflicts are 422 — do not "pick one".
- Query markers are stripped before embedding; `search_query` in the response is the cleaned text.
- Records without `metadata.project_id` never match a scoped search — absence is not a wildcard.
- `LITELLM_LOCAL_MODEL_COST_MAP=True` keeps litellm offline during tests; forgetting it makes tests flaky/network-dependent.
- HTTPX is version-pinned for the FastAPI/Starlette test client — upgrading it breaks the suite.
- Store names and project IDs are independent axes; selecting a store never implies a project scope.

</gotchas>
