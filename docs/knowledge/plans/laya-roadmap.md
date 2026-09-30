---
name: laya-roadmap
title: Laya Integration Roadmap
description: Integration assessment for convaiinnovations/laya decision model covering RAG result guiding, answer formatting/project gating, and additional integration opportunities
tags: ["laya", "roadmap", "rag", "integration"]
type: project
---

# Laya Integration Roadmap for litellm-pgvector

## Summary

[Laya](https://huggingface.co/convaiinnovations/laya) is a multilingual, non-autoregressive System 1 decision model by Convai Innovations (Apache 2.0). Unlike generative LLMs, Laya takes a **state** (text, email, ticket, or JSON) and **typed questions** and returns typed answers with calibrated probabilities in a single forward pass (~33 ms on GPU). It never generates text, so there is nothing to parse or hallucinate. It supports `choice`, `score`, and `noul` (yes/no probability) question types across 100+ languages.

Key properties relevant to this project:

- **421M parameters** (ModernBERT-large backbone + decision head) for English; 322M (mmBERT-base) for multilingual
- **Zero-shot or fine-tuned**: base checkpoints work out of the box; fine-tuning on domain data jumps accuracy dramatically (0.362 → 0.766 on typed-decisions)
- **Self-hostable**: `pip install laya`, Apache 2.0, no API cost
- **HTTP server** (`laya-serve`): Jev-compatible `POST /v1/systemone` endpoint, drop-in deployable
- **LangChain/LangGraph integration**: `laya[langchain]` extra available
- **MCP server**: `laya[mcp]` extra for agent-tool integration
- **High throughput**: 103–332 questions/sec batched on a single T4 GPU

---

## Integration Area 1: RAG Result Guiding and Filtering

**Goal**: Use Laya to classify incoming RAG queries and guide retrieval before embedding search.

### Current State

The `push_to_rag.py` pipeline chunks documents, embeds them with `text-embedding-ada-002`, and stores them in PGVector. Search queries go through `main.py`'s `/v1/vector_stores/{id}/search` endpoint, which performs cosine similarity search with optional `project_id` and metadata filters. There is no semantic classification of the query itself — the system relies entirely on vector similarity and explicit metadata filters.

### Proposed Integration

**Query Classification Gate (pre-retrieval)**

Before executing vector search, run Laya on the incoming query to:

1. **Classify intent**: Determine whether the query is a documentation lookup, an API usage question, a troubleshooting request, or out-of-scope. Route to different vector stores or filter strategies based on classification.

2. **Detect project scope**: When the query does not contain an explicit `project_id` marker, use Laya to infer the most likely project from the query text. This addresses the RAG project-id filtering issue documented in [GitHub issue #2](https://github.com/jdelon02/litellm-pgvector/issues/2).

3. **Confidence gating**: Use Laya's calibrated probability to reject or flag low-confidence classifications. If the model is unsure which project a query belongs to, return results from all projects with a warning rather than silently filtering.

**Implementation sketch**:

```python
from laya import Router

router = Router(preload=True)

def classify_query(query: str) -> dict:
    return router.predict(query, {
        "project": {
            "type": "choice",
            "instructions": "Which project does this query relate to?",
            "criteria": {
                "litellm-pgvector": "vector stores, embeddings, PGVector, RAG, search",
                "scriptwriting": "scripts, episodes, characters, storylines",
                "other": "unrelated or unclear"
            }
        },
        "intent": {
            "type": "choice",
            "instructions": "What is the user trying to do?",
            "criteria": {
                "lookup": "find specific documentation or configuration",
                "troubleshoot": "debug an error or unexpected behavior",
                "howto": "learn how to perform a task",
                "out_of_scope": "not related to this system"
            }
        },
        "confidence_gate": {
            "type": "noul",
            "instructions": "Is the project classification clearly identifiable?"
        }
    })
```

**Where it fits in the stack**: Extend `main.py` directly. The classification gate runs before the existing search logic in the `/v1/vector_stores/{id}/search` endpoint. When a query arrives, Laya classifies it first, then the inferred `project_id` and intent filters are applied to the PGVector query. This keeps the architecture simple — one service, one codebase, no extra proxy or middleware layer.

### Effort Estimate

- **Proof of concept**: 1–2 days. Install `laya`, define classification questions for known projects, measure zero-shot accuracy on sample queries.
- **Fine-tuning**: 3–5 days. Collect a labeled dataset of queries → project/intent from existing RAG logs. Fine-tune using the [Kaggle notebook](https://github.com/NandhaKishorM/laya/blob/main/notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb) approach. Expect accuracy to jump significantly (the model's own benchmarks show 0.362 → 0.766 with fine-tuning).
- **Integration**: 2–3 days. Add the classification gate to `main.py` or a middleware, wire up project inference, add fallback logic.

---

## Integration Area 2: Answer Formatting and Project Gating

**Goal**: Use Laya to validate that search results and generated answers are correctly scoped to the referenced project and meet quality/format requirements.

### Current State

The search endpoint returns raw results with similarity scores and metadata. There is no post-retrieval validation — if the RAG returns content from the wrong project (as documented in issue #2), the consuming LLM or agent receives it without any gate.

### Proposed Integration

**Post-retrieval Classification Gate**

After vector search returns results, run Laya on each result (or a batch summary) to:

1. **Verify project alignment**: Confirm that each returned chunk's content actually matches the declared `project_id` in its metadata. This catches ingestion errors where metadata was stamped incorrectly.

2. **Relevance scoring**: Beyond cosine similarity, use Laya to score whether the chunk is actually relevant to the query's intent. Cosine similarity can return topically adjacent but unhelpful results; Laya's calibrated probabilities provide a complementary signal.

3. **Answer format validation**: For use cases where the consuming LLM must produce answers in a specific format (e.g., API reference style, troubleshooting steps), use Laya to classify whether the retrieved context supports that format.

**Implementation sketch**:

```python
def validate_results(query: str, results: list[dict]) -> list[dict]:
    validated = []
    for result in results:
        check = router.predict(
            {"query": query, "content": result["content"]},
            {
                "relevance": {
                    "type": "score",
                    "instructions": "How relevant is this content to the query?",
                    "criteria": ["not relevant", "somewhat relevant", "directly answers the query"]
                },
                "project_match": {
                    "type": "noul",
                    "instructions": f"Is this content about {result['metadata'].get('project_id', 'unknown')}?"
                }
            }
        )
        if check["answers"]["relevance"]["score"] > 1.0:
            result["laya_relevance"] = check["answers"]["relevance"]["score"]
            result["laya_project_confirmed"] = check["answers"]["project_match"]["noul"] > 0.5
            validated.append(result)
    return validated
```

**Batching advantage**: Laya answers all questions in a single forward pass per state. For a search returning 20 results with 2 questions each, that is 20 forward passes (~790 ms on GPU, ~4s on CPU). For real-time search this is acceptable; for bulk operations, results can be batched with Laya's native multi-question support.

### Effort Estimate

- **Prototype**: 1–2 days. Add post-retrieval validation to the search endpoint.
- **Calibration**: 1–2 days. Fit temperature scaling on domain data to ensure confidence scores are trustworthy.
- **Production hardening**: 2–3 days. Add fallback when Laya is unavailable, handle timeouts, add metrics.

---

## Integration Area 3: Additional Integration Opportunities

### 3a. Ingestion-time Document Classification

**What**: Run Laya during `push_to_rag.py` ingestion to auto-classify documents by type, topic, and quality before embedding.

**Why**: Currently, document metadata (project_id, concept_id, tags) comes from OKF frontmatter. Laya could enrich this with:
- Automatic topic classification for documents lacking frontmatter
- Quality/relevance scoring to flag low-value chunks
- Language detection for multilingual document bundles

**Where**: In `push_to_rag.py` between chunking and embedding. Add classification questions for document type and topic, stamp results into chunk metadata.

### 3b. Query Intent Routing for Multi-model Pipelines

**What**: Use Laya as a lightweight router to decide which model handles a query — fast lookup via RAG vs. deep reasoning via a larger LLM vs. direct answer from cached results.

**Why**: Laya's ~33ms latency makes it ideal as a first-pass classifier. Simple documentation lookups can be served entirely from RAG without invoking a full LLM call. Complex reasoning queries get routed to a more capable (and expensive) model.

**Where**: In the LiteLLM proxy layer or as a middleware in front of the FastAPI app.

### 3c. Guardrails and Content Moderation

**What**: Use Laya's `noul` question type to gate inputs and outputs for safety and policy compliance.

**Why**: Before processing a RAG query or returning results, Laya can check:
- Is the query attempting prompt injection? (with fine-tuning on attack patterns)
- Does the returned content contain sensitive data that should not be surfaced?
- Is the answer within the scope of the declared project?

**Where**: Input validation layer before the search endpoint; output validation after result assembly.

### 3d. Feedback Loop and Continuous Improvement

**What**: Use Laya to classify user feedback on RAG results (thumbs up/down, corrections) and route it back to improve retrieval.

**Why**: When users mark a result as unhelpful, Laya can classify *why* (wrong project, outdated info, irrelevant topic) and use that signal to:
- Adjust retrieval weights
- Flag documents for re-ingestion or removal
- Build fine-tuning datasets for the classification model itself

---

## Architecture Overview

```
User Query
    │
    ▼
┌─────────────────────┐
│  Laya Classification │  (~33ms, pre-retrieval)
│  - Project inference │
│  - Intent routing    │
│  - Confidence gate   │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Vector Search       │  (existing PGVector + cosine similarity)
│  - project_id filter │
│  - metadata filters  │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Laya Validation     │  (~33ms per result, post-retrieval)
│  - Relevance check   │
│  - Project confirm   │
│  - Format gating     │
└────────┬────────────┘
         │
         ▼
    Filtered, validated results → LLM / Agent / Client
```

**Deployment**: Laya runs as a sidecar service via `laya-serve` (Jev-compatible HTTP at port 8001), or embedded directly in the Python process. For this project, embedding in-process avoids an extra network hop and keeps the dependency simple.

---

## Prerequisites and Dependencies

| Requirement | Status | Notes |
|---|---|---|
| Python 3.10+ | Available | Already required by this project |
| `pip install laya` | New dependency | ~808 MB for English checkpoint download on first use |
| GPU (optional) | Recommended | T4 gives 33ms/query; CPU gives 193–464ms/query |
| Fine-tuning data | Needed | Collect from existing RAG query logs + manual labeling |
| Temperature calibration | Needed | Fit on domain data before trusting confidence scores |

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Zero-shot accuracy insufficient for project classification | Medium | Fine-tune on labeled queries; benchmarks show 2x+ improvement |
| Added latency to search path | Low | 33ms on GPU is negligible vs. embedding + DB query time |
| Model download size (~808MB) | Low | One-time; can use quantized versions (48 quantizations available on HF) |
| Calibration drift over time | Medium | Periodic recalibration as new projects/documents are added |
| Laya unavailable (dependency failure) | Medium | All Laya gates should be optional; fall back to existing behavior |

---

## Recommended Next Steps

1. **Install and evaluate** (`pip install laya`): Run zero-shot classification on 50 representative RAG queries from this project. Measure accuracy for project detection and intent classification. (~1 day)

2. **Prototype query gate**: Add a classification step before the search endpoint in `main.py` that infers `project_id` from queries lacking explicit markers. Compare search quality with and without the gate. (~2 days)

3. **Build fine-tuning dataset**: Label 200+ queries with project, intent, and relevance from existing logs. Use the Kaggle notebook to fine-tune a checkpoint. (~3 days)

4. **Integrate post-retrieval validation**: Add Laya-based relevance and project-alignment checks to search results. (~2 days)

5. **Deploy `laya-serve`**: Run Laya as a sidecar HTTP service for production use, or embed in-process for simplicity. (~1 day)

---

## References

- Model card: https://huggingface.co/convaiinnovations/laya
- GitHub: https://github.com/NandhaKishorM/laya
- PyPI: https://pypi.org/project/laya/
- Documentation: https://nandhakishorm.github.io/laya/
- Fine-tuning notebook: https://github.com/NandhaKishorM/laya/blob/main/notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb
- Live demo: https://huggingface.co/spaces/convaiinnovations/laya-demo
- Related issue: [GitHub #2 - RAG project_id filtering bug](https://github.com/jdelon02/litellm-pgvector/issues/2)