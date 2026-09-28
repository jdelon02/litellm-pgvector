---
type: "project-instructions"
title: "SOUL.md"
description: "Project instructions source for litellm-pgvector: SOUL.md."
tags: ["litellm-pgvector", "project"]
source_path: "SOUL.md"
---

# SOUL.md

<soul project="litellm-pgvector" format="hybrid-xml-markdown">
  <identity>
    litellm-pgvector is quiet retrieval infrastructure. It speaks the OpenAI
    Vector Stores dialect so existing clients and gateways work unchanged,
    stores vectors in Postgres/PGVector, and delegates embedding generation to
    a LiteLLM proxy. Other systems (IMS RAG, chat gateways, ingestion hooks)
    depend on its contract staying boring and exact.
  </identity>

  <north_star>
    Be a drop-in, contract-faithful vector store: compatible shapes, precise
    validation, predictable project scoping, and no surprises for callers.
  </north_star>
</soul>

## Operating Philosophy

<principles>

- **Compatibility is the product**: a response field renamed or an error code changed breaks downstream tools silently; treat shapes as frozen contract.
- **Validate loudly, fail early**: ambiguous or conflicting project scoping is a 422 before any database or embedding call, never a guess.
- **Scoping is not security**: `project_id` filtering narrows results; authorization is the caller's problem and the API key's job.
- **Configuration over code**: field mappings, models, and endpoints change via `DB_FIELDS__*` / `EMBEDDING__*` env config, not forks of the source.
- **Hermetic tests are trust**: contract tests run without a database, a Prisma client, or a live proxy — keep it that way.
- **Generated and secret files stay out of git**: `.env`, Prisma client output, and local indexes are environment, not source.

</principles>

## Agent Posture

<agent_posture>

When working in this repo, act like a maintainer of a public API gateway:

- Prefer small, backwards-compatible changes.
- State exactly which endpoints and request shapes a change touches.
- Update README, models, and tests together — a contract change in one place only is a defect.
- Use the graphs to measure blast radius before editing shared request paths.
- When behavior is ambiguous, the README's documented rules are the contract; reconcile code to docs deliberately, not silently.

</agent_posture>

## Boundaries

<boundaries>

### This Project Is

- An OpenAI-compatible Vector Stores API over PGVector.
- The embedding-storage and semantic-search backend for the IMS/RAG ecosystem.
- A LiteLLM-proxy client for embedding generation.
- A home for project-scoped retrieval semantics (`metadata.project_id`).

### This Project Is Not

- An authorization system; project filtering is convenience, not access control.
- An embedding model host; models live behind the LiteLLM proxy.
- A chat or RAG orchestrator; it sees search requests, not conversations.
- A secret store; keys live in `.env` outside version control.

</boundaries>

## Decision Heuristics

<decision_heuristics>

- If a change could alter a response shape or status code, check OpenAI's Vector Stores contract and existing tests first.
- If project-scoping rules change, update README, `models.py` validation, `main.py` behavior, and tests in the same change.
- If a caller's problem can be solved with metadata or config, prefer that over new endpoints.
- If you need structure or blast radius, ask the graphs (`codegraph`, `code-review-graph`) before scanning files.
- If a concept needs background, search the okf bundle (`okf search`) before re-deriving it.
- If a test would need a live service, redesign it to isolate the dependency instead.

</decision_heuristics>

## Success Looks Like

<success_criteria>

- Existing OpenAI-compatible clients work without modification.
- Project-scoped searches return exactly the scoped records, and misuse fails with a clear 422.
- The unittest suite passes without any external service running.
- Future agents can navigate the code through the graphs and the okf bundle without reverse-engineering request flows.

</success_criteria>
