"""
STEP 5 — Retriever with query caching.

Provides a single retrieve() function that:
  1. Embeds the query text.
  2. Searches the FAISS vector store.
  3. Returns the top-k chunk strings.

A small LRU cache prevents redundant embedding + index searches for
repeated or near-duplicate queries (e.g., repeated WebSocket pings).
"""

from __future__ import annotations

import functools
import hashlib
import logging
import pathlib
from typing import List, Optional

from rag.embeddings import get_embedding
from rag import vector_store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache — keyed on (query_hash, top_k) so different k values are cached
# separately.  maxsize=128 keeps memory overhead negligible.
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=128)
def _cached_retrieve(query_hash: str, top_k: int) -> tuple:
    """Internal cached retrieval — keyed by SHA-256 hash of the query."""
    # This is called only when a cache miss occurs.  The actual query text
    # cannot be a cache key directly because lru_cache requires hashable args;
    # the hash stored in the module-level dict is looked up below.
    raise NotImplementedError("Should not be called directly — use retrieve().")


# We use a plain dict as the real cache to store (query → results) because
# lru_cache with a hash key would lose the original query string.
_CACHE: dict = {}
_CACHE_MAX = 128


def _cache_key(query: str, top_k: int) -> str:
    """Stable cache key = SHA-256(normalised_query) + ":k=" + top_k."""
    normalised = " ".join(query.strip().lower().split())
    digest = hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]
    return f"{digest}:k={top_k}"


def _ensure_index_loaded() -> None:
    """
    Attempt to load the persisted FAISS index if it is not yet in memory.
    Builds the index from scratch if no persisted version exists.
    """
    if vector_store.is_index_ready():
        return

    # Try to load from disk first (fast path — no re-embedding needed).
    if vector_store.load_index():
        logger.info("RAG: FAISS index loaded from disk.")
        return

    # Cold-start: generate docs, chunk, embed, build index.
    logger.info("RAG: No persisted index — building from scratch …")
    _build_index_from_docs()


def _build_index_from_docs() -> None:
    """Generate documents, chunk them, embed, and build the FAISS index."""
    import pathlib

    from rag.generate_docs import DOCUMENTS, generate_documents
    from rag.chunker import chunk_text
    from rag.embeddings import embed_batch

    repo_root = pathlib.Path(__file__).resolve().parent.parent
    docs_dir = repo_root / "data" / "docs"

    # Write documents if not already present.
    if not any(docs_dir.glob("doc_*.txt")):
        logger.info("RAG: Generating documents …")
        generate_documents(str(docs_dir))

    # Read and chunk every document.
    all_chunks: List[str] = []
    all_meta: List[dict] = []

    doc_files = sorted(docs_dir.glob("doc_*.txt"))
    for doc_file in doc_files:
        doc_id = doc_file.stem          # e.g. "doc_001"
        text = doc_file.read_text(encoding="utf-8")
        chunks = chunk_text(text)
        for chunk_idx, chunk in enumerate(chunks):
            all_chunks.append(chunk)
            all_meta.append({"doc_id": doc_id, "chunk_id": chunk_idx})

    if not all_chunks:
        logger.error("RAG: No chunks found — index not built.")
        return

    logger.info("RAG: Embedding %d chunks …", len(all_chunks))
    import numpy as np
    embeddings = embed_batch(all_chunks)

    vector_store.build_index(all_chunks, embeddings, metadata=all_meta, persist=True)
    logger.info("RAG: Index built with %d chunks.", len(all_chunks))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def retrieve(query: str, top_k: int = 5) -> List[str]:
    """
    Retrieve the *top_k* most relevant document chunks for *query*.

    Results are cached by query content so repeated identical queries skip
    the embedding and FAISS search steps entirely.

    Args:
        query:  The user's natural-language question.
        top_k:  Number of chunks to return (default 5).

    Returns:
        List[str]: Ordered list of chunk texts (most relevant first).
                   Returns [] if the index is empty or query is blank.
    """
    if not query or not query.strip():
        return []

    _ensure_index_loaded()

    if not vector_store.is_index_ready():
        logger.warning("RAG: Index not available — returning empty context.")
        return []

    key = _cache_key(query, top_k)
    if key in _CACHE:
        logger.debug("RAG cache hit for query: %.60s …", query)
        return _CACHE[key]

    # Embed query and search.
    query_vec = get_embedding(query)
    hits = vector_store.search(query_vec, top_k=top_k)

    chunks = [chunk_text for chunk_text, _meta, _score in hits]

    # Evict oldest entry when cache is full (simple FIFO).
    if len(_CACHE) >= _CACHE_MAX:
        oldest_key = next(iter(_CACHE))
        del _CACHE[oldest_key]

    _CACHE[key] = chunks
    return chunks


def clear_cache() -> None:
    """Remove all cached retrieval results (useful in tests)."""
    _CACHE.clear()


def prewarm() -> bool:
    """
    Preload index and embedding model to avoid first-request latency spikes.

    Returns:
        bool: True if warmup completed successfully.
    """
    try:
        _ensure_index_loaded()
        if not vector_store.is_index_ready():
            return False

        # Warm sentence-transformers model and FAISS search path.
        _ = get_embedding("hotel booking")
        _ = retrieve("hotel booking", top_k=1)
        return True
    except Exception:
        return False
