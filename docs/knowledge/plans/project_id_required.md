---
name: project_id_required
title: Make project_id Filtering Required for Search Results
description: Implementation plan for issue #6 - returning empty results when project_id is not provided
tags: ["search", "filtering", "security", "project-scoping"]
type: plan
---

# Plan: Make project_id Filtering Required for Search Results

## Issue
GitHub issue: #6

Currently, the `/vector_stores/{id}/search` endpoint returns all matches when no `project_id` is provided. This is problematic because:

1. Searches without `project_id` return results from all projects mixed together
2. The RAG ingestion pipeline expects project-scoped results only
3. There's a security/consistency concern: unscoped searches expose data from multiple projects

## Desired Behavior

**If no `project_id` is provided** (either via `.env` default `PROJECT_ID` or an in-chat query marker), **return no results** (empty list).

**If `project_id` is provided** (from env or marker), filter results by that project.

## Current State Analysis

### Key Code Paths

1. **Search endpoint** (`main.py:236-331`):
   - Lines 283-297: Project filtering logic
   - Currently only applies filters when `filters` dict is non-empty
   - When `request.project_id` is `None`, no `project_id` filter is added
   - Query returns all embeddings in the vector store

2. **Request validation** (`models.py:59-87`):
   - `project_id` defaults to `None`
   - Validates that if provided, it must be non-empty
   - Validates conflict between `project_id` and `filters.project_id`
   - Parses query markers for project_id

3. **Config** (`config.py`):
   - `DB_FIELDS__PROJECT_ID` configurable field name
   - Default: `"project_id"`

### Current SQL Query Structure

```sql
SELECT ... FROM embeddings 
WHERE vector_store_id = $1
-- No project_id filter when request.project_id is None
ORDER BY distance ASC LIMIT ...
```

## Implementation Plan

### Step 1: Change Search Filtering Logic

**File**: `main.py` (lines 283-297)

**Change**: Always apply `project_id` filter when searching. Default to empty string if not provided.

```python
# Current (lines 283-297)
filter_conditions = []
filters = dict(request.filters or {})
if request.project_id is not None:
    filters["project_id"] = request.project_id

if filters:
    for key, value in filters.items():
        filter_conditions.append(f"{fields.metadata_field}->>${param_count} = ${param_count + 1}")
        query_params.extend([key, str(value)])
        param_count += 2

if filter_conditions:
    base_query += " AND " + " AND ".join(filter_conditions)

# Proposed change
# Always apply project_id filter for security/scoping
project_id = request.project_id
if request.filters and "project_id" in request.filters:
    if project_id is None:
        project_id = request.filters["project_id"]
    elif project_id != request.filters["project_id"]:
        raise HTTPException(
            status_code=422,
            detail="Conflicting project_id in project_id field and filters"
        )

# If still no project_id, return empty results
if project_id is None:
    base_query += " AND FALSE"  # Returns empty set immediately

filter_conditions = []
if project_id is not None:
    filter_conditions.append(f"{fields.metadata_field}->>'{fields.project_id_field}' = ${param_count}")
    query_params.append(str(project_id))
    param_count += 1

if filter_conditions:
    base_query += " AND " + " AND ".join(filter_conditions)
```

### Step 2: Update Search Request Model (Optional)

**File**: `models.py`

Consider changing default from `None` to empty string or requiring `project_id`:

```python
# Option 1: Require project_id explicitly
class VectorStoreSearchRequest(BaseModel):
    project_id: str  # No Optional, must be provided

# Option 2: Default to empty (matches "no results" behavior)
class VectorStoreSearchRequest(BaseModel):
    project_id: Optional[str] = ""  # Empty string = no matches
```

**Recommendation**: Option 2 is safer - maintains backward compatibility while achieving the desired behavior. A `None` value should be converted to `""` (empty string) which won't match any metadata.

### Step 3: Update Tests

**File**: `tests/test_project_filter.py`

Add tests for:
1. `test_search_without_project_id_returns_empty` - verify empty results when no project_id
2. `test_search_with_project_id_filters_correctly` - verify filtering works
3. `test_search_with_empty_project_id_returns_empty` - verify empty string returns no results

### Step 4: Update Documentation

**File**: `README.md`

Update the `project_id` parameter documentation:
> If not provided, the search will return no results. To search a specific project, provide the `project_id` value.

## Security Impact

- **Positive**: Prevents accidental cross-project data leakage
- **Positive**: Aligns with the RAG ingestion expectation of project-scoped data
- **Breaking**: Existing clients that don't send `project_id` will now get empty results (which is the desired fix)

## Testing Strategy

1. Mock tests (already in `tests/test_project_filter.py`)
2. Run contract tests: `python -m unittest discover -s tests -v`
3. Manual test with `curl` or Postman against local server

## Rollback Plan

If issues arise:
1. The change is isolated to `main.py:search_vector_store`
2. Reverting to `request.project_id is None` check restores old behavior
3. No database migrations required
