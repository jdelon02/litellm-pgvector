---
name: rag-ingestion
title: RAG Ingestion Pipeline
description: Document the push_to_rag.py chunking and embedding pipeline
tags: ["rag", "documentation", "ingestion", "vector-store"]
type: project
---

# RAG Ingestion Pipeline

## Overview

The `scripts/push_to_rag.py` script ingests documentation from the `docs/knowledge/` bundle into an OpenAI-compatible vector store backed by PGVector. It uses the `okf` CLI to discover and read knowledge documents, chunks them intelligently, generates embeddings via LiteLLM proxy or NanoGPT API, and uploads them in batches.

## Key Components

### 1. Chunking Strategy

**Location**: `scripts/push_to_rag.py` lines 123-155

The `chunk_text()` function implements intelligent document splitting:

- **Heading-based boundaries**: Splits on Markdown headings (`#` through `######`) outside fenced code blocks
- **Code fence awareness**: Tracks triple-backtick or tilde fences to avoid splitting inside code blocks
- **Size constraints**: Default max 3000 characters per chunk (configurable via `--chunk-chars`)
- **Boundary preference**: For oversized sections, prefers paragraph boundaries (`\n\n`), then line boundaries (`\n`)
- **Content preservation**: Retains section titles in metadata for context

### 2. Metadata Structure

Each chunk carries rich provenance information:

```python
{
    "project_id": str,           # PROJECT_ID env var (content boundary)
    "concept_id": str,           # OKF concept identifier
    "filename": str,             # Source file name
    "source_path": str,          # Path relative to repo root
    "source_tool": str,          # Always 'okf'
    "embedding_model": str,      # e.g., 'text-embedding-ada-002'
    "section": str,              # Heading text from source
    "chunk_index": int,          # Zero-based index within document
    "chunk_id": str,             # SHA-256 hash of content + metadata
    # Plus optional OKF fields: title, type, tags, status, trust_tier, stale
}
```

### 3. Upload Flow

The pipeline executes in four phases:

1. **Discovery**: `okf list` discovers all concepts in `docs/knowledge/`
2. **Collection**: `okf show` retrieves each concept's body and metadata
3. **Embedding**: Text chunks are batched (default 16 per request) and sent to embedding service
4. **Insertion**: Vectors + metadata posted to `/v1/vector_stores/{store_id}/embeddings/batch`

### 4. Configuration

Required environment variables in `.env`:

```dotenv
NANOGPT_API_KEY=<API key for embedding requests>
rag_base_url=https://your-vector-store-host
rag_api_key=<vector store API key>
PROJECT_ID=<project id, e.g. litellm_pgvector>      # also the vector store name
rag_batch_size=16                      # Optional, default 16
```

Alternative configuration via command-line flags:
- `--hermes-config`: Override Hermes YAML path (for legacy credential fallback)
- `--chunk-chars`: Override chunk size (minimum 100)
- `--batch-size`: Override embedding batch size (1-2048)
- `--dry-run`: Inspect OKF only; no network or state writes
- `--hook`: Pre-commit mode; refreshes OKF indexes before upload

### 5. State Management

**Location**: `.rag/<hash>.json` (Git-ignored)

The script maintains persistent upload state:

```json
{
    "uploaded": {
        "<chunk_id>": true,
        ...
    },
    "pending": ["<chunk_id>", ...]  # Present only during active upload
}
```

**Key behaviors**:
- Repeated runs skip already-uploaded chunks (identified by content/metadata hash)
- Each unique combination of vector URL, store name, embedding URL, and model gets its own state file
- Pending batches prevent concurrent uploads and provide crash recovery
- Old chunks remain searchable even when removed from source (append-only API)

### 6. Error Handling

#### Credential Errors
- Missing `NANOGPT_API_KEY`: Fails with setup instructions
- Missing `rag_api_key`: Falls back to `model.api_key` in Hermes config
- Unresolved `${VAR}` references: Fails pointing to the specific reference

#### Network Errors
- Embedding HTTP 429/5xx: Retries up to 3 times with exponential backoff
- Vector store connection failures: Immediate failure with diagnostic message
- Timeout (90s default): Propagates with retry suggestion

#### Data Errors
- Staged Markdown changes: Blocks upload to prevent partial document ingestion
- Ambiguous store names: Requires unique match within first 100 stores
- Invalid embeddings: Validates dimension count and finite values

### 7. Integration Points

#### Pre-commit Hook
Called from `.githooks/pre-commit` when `docs/` changes are staged:
```bash
python3 scripts/push_to_rag.py --hook
```

This sequence:
1. Refreshes OKF indexes via `sync_knowledge.py`
2. Stages changed `index.md` files
3. Validates no staged Markdown diffs exist
4. Collects chunks and uploads new ones
5. Skips upload if primary store name is empty

#### Script Sync
[`scripts/sync_knowledge.py`](../../scripts/sync_knowledge.py) generates `index.md` navigation files for the OKF bundle based on frontmatter metadata.

## Usage Examples

### Dry Run (inspection only)
```bash
python3 scripts/push_to_rag.py --dry-run
# Output: OKF: X documents, Y chunks; model text-embedding-ada-002, 1536 dimensions.
```

### Full Upload
```bash
python3 scripts/push_to_rag.py
# Progress: "Embedding batch 1/N: M texts; model..."
# Progress: "Uploaded X/Y new chunks."
# Final: "Complete: X new chunks uploaded; Y already confirmed locally."
```

### Custom Parameters
```bash
python3 scripts/push_to_rag.py --chunk-chars 2000 --batch-size 32
```

### Debug Mode
```bash
RAG_DEBUG=true python3 scripts/push_to_rag.py
# Prints HTTP request details (with secrets redacted) to stderr
```

## Limitations

1. **Append-only backend**: Deleted or modified source chunks are re-uploaded as new entries; old versions remain searchable
2. **No server-side upsert**: Cannot replace existing chunks atomically
3. **Store lookup limit**: Requires primary store to be findable within first 100 stores
4. **Single writer**: File lock prevents concurrent uploads from multiple processes
5. **Chunk hash stability**: Changing any metadata field (even unused OKF fields) creates a new chunk ID

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Missing RAG configuration` | `.env` not created or incomplete | Create `.env` following template in error message |
| `Another RAG upload is already running` | Previous process holds lock file | Verify no stuck process; remove `.rag/upload.lock` if safe |
| `Vector-store listing is incomplete` | More than 100 stores configured | Consolidate stores or use exact `PROJECT_ID` |
| `Stage or stash Markdown changes` | Working tree has unstaged `.md` edits | `git add` or `git stash` before running |
| Empty search results | Documents ingested without matching `project_id` | Verify `metadata.project_id` was stamped during ingestion |

## Future Enhancements

- [ ] Implement upsert semantics for chunk replacement
- [ ] Add deletion support for removed documents
- [ ] Support custom chunking strategies per document type
- [ ] Multi-file parallel uploading with progress tracking
- [ ] Automatic store creation fallback (already exists in dev)
- [ ] Parent-child chunk relationships for hierarchical context

