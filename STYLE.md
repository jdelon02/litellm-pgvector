---
type: "project-instructions"
title: "STYLE.md"
description: "Project instructions source for litellm-pgvector: STYLE.md."
tags: ["litellm-pgvector", "project"]
source_path: "STYLE.md"
---

# STYLE.md

<style_guide project="litellm-pgvector" format="hybrid-xml-markdown">
  <purpose>
    Keep code, API surface, tests, and documentation consistent with the
    repo's role as contract-faithful retrieval infrastructure.
  </purpose>
</style_guide>

## Python Style

<python>

- FastAPI idioms: async endpoints, Pydantic models for every request/response body, dependency-injected auth.
- All request/response shapes live in `models.py`; endpoints in `main.py` stay thin and delegate.
- Configuration only through `config.py` (pydantic-settings, `__` nested delimiter, `.env`); never read `os.environ` ad hoc in endpoint code.
- Keep network calls (LiteLLM proxy) inside `embedding_service.py`, explicit and timeout-aware.
- Validation errors are HTTP 422 with a message naming the offending field or marker; raise before touching the database or the proxy.
- Type-annotate non-trivial helpers; prefer explicit over clever.

</python>

## API Style

<api>

- OpenAI Vector Stores compatibility first: `object` discriminators, list envelopes (`first_id`, `last_id`, `has_more`), and error semantics match the upstream API.
- New capabilities are additive and optional (as `project_id` was); omitted fields preserve prior behavior exactly.
- Both `/v1/...` and legacy unprefixed routes stay in sync when either changes.
- Document every accepted request variation (top-level field, filter, query marker) with its precedence and conflict rules.

</api>

## Test Style

<tests>

- `unittest` via `python -m unittest discover -s tests`; keep `LITELLM_LOCAL_MODEL_COST_MAP=True` in documented commands.
- Tests are hermetic: fake the Prisma layer and embedding calls; never require a generated client or live services.
- Every documented validation rule (422 cases, marker parsing, scoping precedence) gets an explicit test.
- Pin test-client-sensitive dependencies (HTTPX) as `requirements-dev.txt` does; do not upgrade casually.

</tests>

## Documentation Style

<docs>

- Use Markdown headings for scanability and XML-style tags for durable instruction sections in root instruction files.
- `README.md` is the caller-facing contract: keep curl examples copy-pasteable and response JSON exact.
- Only the bundle-root `docs/knowledge/index.md` carries `okf_version` frontmatter; subdirectory `index.md` files must have none (OKF §8). Run `okf validate docs/knowledge/` after editing and `okf index docs/knowledge/` after adding or moving documents.
- Update `AGENTS.md`/`MEMORY.md` when behavior, commands, or invariants change; stale instruction files are defects.

</docs>

## Change Scope

<change_scope>

- Keep edits tightly related to the requested change; contract code rewards surgical diffs.
- A contract change lands in `models.py`, `main.py`, `README.md`, and `tests/` together.
- Leave generated artifacts (`.env`, Prisma client output, graph indexes) out of commits.
- After committing substantive changes, refresh the graphs: `codegraph sync && code-review-graph update`.

</change_scope>
