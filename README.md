# OpenAI Vector Stores API with PGVector

A FastAPI application that provides OpenAI-compatible vector store endpoints using PGVector and LiteLLM proxy for embeddings.

## Features

- 🔌 OpenAI-compatible API endpoints
- 🗄️ PGVector for efficient vector storage and similarity search
- 🎛️ Configurable database field mappings
- 🔄 LiteLLM proxy integration for any embedding model
- 🐳 Docker support
- ⚡ FastAPI with async support

## API Endpoints

### 1. Create Vector Store
```bash
curl -X POST \
  http://localhost:8000/v1/vector_stores \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Support FAQ"
  }'
```

### 2. List Vector Stores
```bash
# List all vector stores
curl -X GET \
  http://localhost:8000/v1/vector_stores \
  -H "Authorization: Bearer your-api-key"

# List with pagination (limit and after parameters)
curl -X GET \
  "http://localhost:8000/v1/vector_stores?limit=10&after=vs_abc123" \
  -H "Authorization: Bearer your-api-key"
```

### 3. Add Single Embedding to Vector Store
```bash
curl -X POST \
  http://localhost:8000/v1/vector_stores/vs_abc123/embeddings \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Our return policy allows returns within 30 days of purchase.",
    "embedding": [0.1, 0.2, 0.3, ...],
    "metadata": {
      "category": "returns",
      "source": "faq",
      "id": "return_policy_1"
    }
  }'
```

### 4. Add Multiple Embeddings (Batch)
```bash
curl -X POST \
  http://localhost:8000/v1/vector_stores/vs_abc123/embeddings/batch \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "embeddings": [
      {
        "content": "Our return policy allows returns within 30 days of purchase.",
        "embedding": [0.1, 0.2, 0.3, ...],
        "metadata": {"category": "returns"}
      },
      {
        "content": "Shipping is free for orders over $50.",
        "embedding": [0.4, 0.5, 0.6, ...],
        "metadata": {"category": "shipping"}
      }
    ]
  }'
```

### 5. Search Vector Store
```bash
curl -X POST \
  http://localhost:8000/v1/vector_stores/vs_abc123/search \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is the return policy?",
    "limit": 20,
    "filters": {"category": "support"}
  }'
```

## Configuration

### Optional project-scoped search

Both `/v1/vector_stores/{id}/search` and `/vector_stores/{id}/search` accept
an optional top-level `project_id`:

```bash
curl -X POST http://localhost:8000/v1/vector_stores/vs_abc123/search \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the writer authorship rules?",
    "project_id": "scriptwriting",
    "filters": {"category": "rules"},
    "limit": 5
  }'
```

Store the project identifier in each embedding's `metadata.project_id` during
ingestion. A non-null search `project_id` adds an exact metadata equality filter,
combined with other filters using AND, before ordering and limiting results.
Records with missing or null `metadata.project_id` do not match a specified project.
No database schema change is needed.

- Omitted or `null` `project_id`: existing search behavior, including any supplied filters.
- Empty or whitespace-only string: HTTP 422.
- Conflicting top-level `project_id` and `filters.project_id`: HTTP 422.
- Matching values in both locations: accepted and applied once.

Nonempty identifiers are matched exactly; surrounding whitespace is not trimmed.
Existing clients can continue using `filters.project_id`. A gateway must forward
the new field to use the shorthand; this backend change alone does not change
LiteLLM Proxy forwarding. Optional project filtering is not authorization.

### Project markers in search text

The backend also recognizes explicit markers inside the `query` string:

```json
{"query": "project_id: scriptwriting What can the Artist author?"}
```

Supported forms include `project_id: scriptwriting`, `project ID=scriptwriting`,
and `project: scriptwriting`. Keywords are case-insensitive; identifiers remain
case-sensitive. Both `:` and `=` are accepted, with optional spaces/tabs. Bare
identifiers contain letters, numbers, underscores, periods, or hyphens. Quote
names containing spaces: `project: "My Project"`. Values must be on the same
line as the marker and followed by whitespace, the end of the query, or a
supported separator (comma, semicolon, question/exclamation mark, or brackets).

Markers can appear anywhere in the query. They are removed before embedding;
the response's `search_query` contains the cleaned query. Repeated identical
markers are accepted. Conflicting markers, a conflict with explicit `project_id`
or `filters.project_id`, malformed/blank markers, and marker-only queries return
HTTP 422 before database or embedding calls. Queries without a marker keep their
existing behavior. Marker syntax is reserved even when discussing a literal
example; this parser does not infer scope from ordinary prose.

The backend sees the search request, not the original chat conversation. A chat
app must forward the marker in `query` or send a structured `project_id`. Store
names and project IDs are separate: selecting store `delongpa_channel` does not
change metadata `project_id` on its documents. For example, this ingestion test's
`scriptwriting` documents require `project_id: scriptwriting` in that store.

### Search contract tests

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
LITELLM_LOCAL_MODEL_COST_MAP=True python -m unittest discover -s tests -v
```

These tests exercise both HTTP routes and request validation while isolating
database and embedding calls. They do not require a generated Prisma client or
contact live services. The HTTPX version is pinned for this FastAPI/Starlette
version's test client.

### Environment Variables

Create a `.env` file with the following configuration:

```bash
# Database Configuration
DATABASE_URL="postgresql://username:password@localhost:5432/vectordb?schema=public"

# API Configuration
SERVER_API_KEY="your-api-key-here"

# Server Configuration
HOST="0.0.0.0"
PORT=8000

# LiteLLM Proxy Configuration
EMBEDDING__MODEL="text-embedding-ada-002"
EMBEDDING__BASE_URL="http://localhost:4000"
EMBEDDING__API_KEY="sk-1234"
EMBEDDING__DIMENSIONS=1536

# Database Field Configuration (optional)
DB_FIELDS__ID_FIELD="id"
DB_FIELDS__CONTENT_FIELD="content"
DB_FIELDS__METADATA_FIELD="metadata"
DB_FIELDS__EMBEDDING_FIELD="embedding"
DB_FIELDS__VECTOR_STORE_ID_FIELD="vector_store_id"
DB_FIELDS__CREATED_AT_FIELD="created_at"
```

### Database Field Mapping

You can customize the database field names by setting environment variables:

- `DB_FIELDS__ID_FIELD` - Primary key field (default: "id")
- `DB_FIELDS__CONTENT_FIELD` - Text content field (default: "content")
- `DB_FIELDS__METADATA_FIELD` - JSON metadata field (default: "metadata")
- `DB_FIELDS__EMBEDDING_FIELD` - Vector embedding field (default: "embedding")
- `DB_FIELDS__VECTOR_STORE_ID_FIELD` - Foreign key field (default: "vector_store_id")
- `DB_FIELDS__CREATED_AT_FIELD` - Timestamp field (default: "created_at")

### LiteLLM Proxy Configuration

The application uses LiteLLM proxy for embeddings. Configure it with:

- `EMBEDDING__MODEL` - Model name (e.g., "text-embedding-ada-002")
- `EMBEDDING__BASE_URL` - LiteLLM proxy URL (e.g., "http://localhost:4000")
- `EMBEDDING__API_KEY` - LiteLLM proxy API key
- `EMBEDDING__DIMENSIONS` - Embedding dimensions (default: 1536)

## Setup and Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Database Setup

```bash
# Generate Prisma client
prisma generate

# Run database migrations
prisma db push
```

### 3. Set up LiteLLM Proxy

Start LiteLLM proxy pointing to your preferred embedding model:

```bash
# Example: Start LiteLLM proxy for OpenAI
litellm --model text-embedding-ada-002 --port 4000
```

### 4. Run the Application

```bash
python main.py
```

Or using uvicorn directly:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## Docker Deployment

### Build and run with Docker:

```bash
# Build the image
docker build -t vector-store-api .

# Run the container
docker run -p 8000:8000 --env-file .env vector-store-api
```

## Database Schema

The application uses two main tables:

### vector_stores
- `id` (string, primary key)
- `name` (string)
- `file_counts` (json)
- `status` (string)
- `usage_bytes` (integer)
- `created_at` (timestamp)
- `expires_after` (json, optional)
- `expires_at` (timestamp, optional)
- `last_active_at` (timestamp, optional)
- `metadata` (json, optional)

### embeddings
- `id` (string, primary key)
- `vector_store_id` (string, foreign key)
- `content` (string)
- `embedding` (vector(1536))
- `metadata` (json, optional)
- `created_at` (timestamp)

## Supported Models

Any embedding model supported by LiteLLM proxy can be used. Examples:

- OpenAI: `text-embedding-ada-002`, `text-embedding-3-small`, `text-embedding-3-large`
- Cohere: `embed-english-v3.0`, `embed-multilingual-v3.0`
- Voyage: `voyage-2`, `voyage-large-2`
- And many more...

## API Response Format

### Vector Store Response
```json
{
  "id": "vs_abc123",
  "object": "vector_store",
  "created_at": 1699024800,
  "name": "Support FAQ",
  "usage_bytes": 0,
  "file_counts": {
    "in_progress": 0,
    "completed": 0,
    "failed": 0,
    "cancelled": 0,
    "total": 0
  },
  "status": "completed",
  "metadata": {}
}
```

### Vector Store List Response
```json
{
  "object": "list",
  "data": [
    {
      "id": "vs_abc123",
      "object": "vector_store",
      "created_at": 1699024800,
      "name": "Support FAQ",
      "usage_bytes": 1024,
      "file_counts": {"completed": 5, "total": 5},
      "status": "completed",
      "metadata": {}
    }
  ],
  "first_id": "vs_abc123",
  "last_id": "vs_def456",
  "has_more": false
}
```

### Search Response
```json
{
  "object": "vector_store.search",
  "data": [
    {
      "id": "emb_123",
      "content": "Return policy text...",
      "score": 0.95,
      "metadata": {"category": "support"}
    }
  ],
  "usage": {
    "total_tokens": 1
  }
}
```

## Example Search Request

```bash
curl -X POST \
  http://localhost:8000/v1/vector_stores/vs_support_faq/search \
  -H "Authorization: Bearer sk-1234" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How do I return an item?",
    "limit": 5,
    "return_metadata": true
  }'
```

## Health Check

```bash
curl http://localhost:8000/health
```

## Migrating Existing Data

If you have an existing database with embeddings and content, you can easily migrate using the embedding APIs:

### 1. Create Vector Store
First, create a vector store for your data:

```bash
curl -X POST \
  http://localhost:8000/v1/vector_stores \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Migrated Data",
    "metadata": {"source": "legacy_system"}
  }'
```

### 2. Batch Insert Embeddings
Use the batch endpoint to efficiently insert multiple embeddings:

```bash
curl -X POST \
  http://localhost:8000/v1/vector_stores/vs_your_id/embeddings/batch \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "embeddings": [
      {
        "content": "Your text content here",
        "embedding": [0.1, 0.2, 0.3, ...1536 dimensions...],
        "metadata": {"source_id": "doc_123", "category": "support"}
      }
    ]
  }'
```

### 3. Migration Script Example

Here's a Python script example for migrating from an existing database:

```python
import psycopg2
import requests
import json

# Connect to your existing database
conn = psycopg2.connect("your_existing_db_url")
cur = conn.cursor()

# Fetch existing data
cur.execute("SELECT content, embedding, metadata FROM your_table")
rows = cur.fetchall()

# Prepare batch data
embeddings = []
for content, embedding, metadata in rows:
    embeddings.append({
        "content": content,
        "embedding": embedding.tolist(),  # Convert numpy array to list
        "metadata": metadata or {}
    })

# Send batch to API
response = requests.post(
    "http://localhost:8000/v1/vector_stores/your_vector_store_id/embeddings/batch",
    headers={
        "Authorization": "Bearer your-api-key",
        "Content-Type": "application/json"
    },
    json={"embeddings": embeddings}
)

print(f"Migrated {len(embeddings)} embeddings")
```

## License

MIT License
