from typing import Optional, Dict, Any, List
from pydantic import BaseModel, field_validator, model_validator
from datetime import datetime
import re


PROJECT_MARKER = re.compile(r"(?<![\w.])project(?:_id|[ \t]+id)?[ \t]*[:=][ \t]*", re.IGNORECASE)
PROJECT_VALUE = re.compile(r'''(?:"([^"\r\n]+)"|'([^'\r\n]+)'|([\w.-]+))(?=$|[\s,;!?()\[\]{}])''')


def extract_project_marker(query: str):
    """Parse explicit scope markers, preserving unmarked queries verbatim."""
    project_id = None
    pieces = []
    position = 0
    while marker := PROJECT_MARKER.search(query, position):
        value = PROJECT_VALUE.match(query, marker.end())
        if value is None:
            raise ValueError("Project marker requires an identifier or quoted name on the same line")
        name = next(group for group in value.groups() if group is not None)
        if not name.strip():
            raise ValueError("Project marker must not be blank")
        if project_id is not None and name != project_id:
            raise ValueError("Query contains conflicting project markers")
        project_id = name
        pieces.append(query[position:marker.start()])
        position = value.end()
    if project_id is None:
        return query, None
    pieces.append(query[position:])
    cleaned = re.sub(r"\s+", " ", " ".join(pieces)).strip()
    if not cleaned.strip(",;!?.()[]{} "):
        raise ValueError("Search query must contain text beyond the project marker")
    return cleaned, project_id


class VectorStoreCreateRequest(BaseModel):
    name: str
    file_ids: Optional[List[str]] = None
    expires_after: Optional[Dict[str, Any]] = None
    chunking_strategy: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


class VectorStoreResponse(BaseModel):
    id: str
    object: str = "vector_store"
    created_at: int
    name: str
    usage_bytes: int
    file_counts: Dict[str, int]
    status: str
    expires_after: Optional[Dict[str, Any]] = None
    expires_at: Optional[int] = None
    last_active_at: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


class VectorStoreSearchRequest(BaseModel):
    query: str
    project_id: Optional[str] = None
    limit: Optional[int] = 20
    filters: Optional[Dict[str, Any]] = None
    return_metadata: Optional[bool] = True

    @field_validator("project_id")
    @classmethod
    def validate_project_id(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("project_id must be a nonempty string or null")
        return value

    @model_validator(mode="after")
    def validate_project_filter(self):
        query, marker_project = extract_project_marker(self.query)
        if marker_project is not None:
            if self.project_id is not None and self.project_id != marker_project:
                raise ValueError("Query project marker conflicts with project_id")
            self.project_id = marker_project
            self.query = query
        if (self.project_id is not None and self.filters is not None
                and "project_id" in self.filters
                and self.filters["project_id"] != self.project_id):
            raise ValueError("project_id conflicts with filters.project_id")
        return self


class ContentChunk(BaseModel):
    type: str = "text"
    text: str


class SearchResult(BaseModel):
    file_id: str
    filename: str
    score: float
    attributes: Optional[Dict[str, Any]] = None
    content: List[ContentChunk]


class VectorStoreSearchResponse(BaseModel):
    object: str = "vector_store.search_results.page"
    search_query: str
    data: List[SearchResult]
    has_more: bool = False
    next_page: Optional[str] = None


class EmbeddingCreateRequest(BaseModel):
    content: str
    embedding: List[float]
    metadata: Optional[Dict[str, Any]] = None


class EmbeddingResponse(BaseModel):
    id: str
    object: str = "embedding"
    vector_store_id: str
    content: str
    metadata: Optional[Dict[str, Any]] = None
    created_at: int


class EmbeddingBatchCreateRequest(BaseModel):
    embeddings: List[EmbeddingCreateRequest]


class EmbeddingBatchCreateResponse(BaseModel):
    object: str = "embedding.batch"
    data: List[EmbeddingResponse]
    created: int


class VectorStoreListResponse(BaseModel):
    object: str = "list"
    data: List[VectorStoreResponse]
    first_id: Optional[str] = None
    last_id: Optional[str] = None
    has_more: bool = False
