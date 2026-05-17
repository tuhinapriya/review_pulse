from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_author, get_db
from app.db.models import Author
from app.llm.client import get_embedding_provider
from app.schemas.common import SearchRequest, SearchResult

router = APIRouter()


@router.post("/authors/{author_id}/search", response_model=list[SearchResult])
async def semantic_search(
    author_id: UUID,
    body: SearchRequest,
    current_author: Annotated[Author, Depends(get_current_author)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    """Semantic search across the author's entire catalog (F4).

    Embeds the query with the same model used for review embeddings, then
    finds the top-K reviews by cosine similarity using pgvector's <=> operator.
    The JOIN on books.author_id scopes results to the requesting author's
    catalog — an author cannot search another author's reviews.
    """
    if author_id != current_author.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return await _semantic_search(author_id, body, db)


@router.post("/search", response_model=list[SearchResult])
async def semantic_search_my_catalog(
    body: SearchRequest,
    current_author: Annotated[Author, Depends(get_current_author)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    """Semantic search across the signed-in author's catalog."""
    return await _semantic_search(current_author.id, body, db)


async def _semantic_search(
    author_id: UUID,
    body: SearchRequest,
    db: AsyncSession,
) -> list[dict]:
    embedder = get_embedding_provider()
    query_embedding = await embedder.generate_embedding(body.query)

    # Cap k to prevent abuse on large datasets
    k = min(body.k or 10, 50)

    result = await db.execute(
        text("""
            SELECT
                r.id::text AS review_id,
                b.id::text AS book_id,
                b.title AS book_title,
                r.reviewer_name,
                r.body,
                -- Convert distance (0=identical, 2=opposite) to similarity (0-1)
                1 - (r.embedding <=> CAST(:query_vec AS vector)) AS similarity,
                r.sentiment,
                r.rating
            FROM reviews r
            JOIN books b ON r.book_id = b.id
            WHERE b.author_id = :author_id
              AND r.embedding IS NOT NULL
            ORDER BY r.embedding <=> CAST(:query_vec AS vector)
            LIMIT :k
        """),
        {
            "query_vec": str(query_embedding),
            "author_id": str(author_id),
            "k": k,
        },
    )

    return [dict(row) for row in result.mappings().all()]
