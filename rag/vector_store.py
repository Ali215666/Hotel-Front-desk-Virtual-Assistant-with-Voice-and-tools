"""
STEP 4 — FAISS vector store.

Stores chunk embeddings in an IndexFlatIP (inner-product / cosine) index.
Each entry maps to a chunk text and metadata (doc_id, chunk_id).

The index is persisted to disk so that the server does not re-embed on
every restart.
"""

from __future__ import annotations

import json
import logging
import pathlib
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state (in-process singleton)
# ---------------------------------------------------------------------------
_faiss_index = None          # faiss.IndexFlatIP
_chunk_texts: List[str] = []
_metadata: List[Dict[str, Any]] = []

# Default persistence paths (relative to repo root).
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_DEFAULT_INDEX_DIR = _REPO_ROOT / "data" / "index"
_INDEX_FILE = _DEFAULT_INDEX_DIR / "faiss.index"
_META_FILE = _DEFAULT_INDEX_DIR / "metadata.json"
_CHUNKS_FILE = _DEFAULT_INDEX_DIR / "chunks.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_faiss():
    try:
        import faiss  # type: ignore
        return faiss
    except ImportError as exc:
        raise ImportError(
            "faiss-cpu is not installed.  Run: pip install faiss-cpu"
        ) from exc


def _normalise(vectors: np.ndarray) -> np.ndarray:
    """L2-normalise rows so that IndexFlatIP computes cosine similarity."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)  # avoid division by zero
    return (vectors / norms).astype(np.float32)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_index(
    chunks: List[str],
    embeddings: np.ndarray,
    metadata: Optional[List[Dict[str, Any]]] = None,
    persist: bool = True,
    index_dir: Optional[pathlib.Path] = None,
) -> None:
    """
    Build (or rebuild) the in-memory FAISS index from pre-computed embeddings.

    Args:
        chunks:     List of chunk text strings (same order as *embeddings*).
        embeddings: 2-D float32 array of shape (N, dim).
        metadata:   Optional list of dicts with at least {"doc_id", "chunk_id"}.
                    If None, synthetic metadata is generated.
        persist:    If True, save index + payloads to disk.
        index_dir:  Directory for persisted files (default: data/index/).
    """
    global _faiss_index, _chunk_texts, _metadata

    faiss = _import_faiss()

    if len(chunks) != embeddings.shape[0]:
        raise ValueError(
            f"chunks ({len(chunks)}) and embeddings ({embeddings.shape[0]}) length mismatch."
        )

    dim = embeddings.shape[1]
    normed = _normalise(embeddings)

    index = faiss.IndexFlatIP(dim)
    index.add(normed)  # type: ignore[attr-defined]

    _faiss_index = index
    _chunk_texts = list(chunks)
    _metadata = metadata if metadata is not None else [
        {"doc_id": f"doc_{i:03d}", "chunk_id": i} for i in range(len(chunks))
    ]

    logger.info("FAISS index built: %d vectors, dim=%d", index.ntotal, dim)

    if persist:
        _persist(index_dir or _DEFAULT_INDEX_DIR, normed)


def _persist(index_dir: pathlib.Path, normed_vectors: np.ndarray) -> None:
    """Save index, chunk texts, and metadata to disk."""
    faiss = _import_faiss()
    index_dir.mkdir(parents=True, exist_ok=True)

    faiss.write_index(_faiss_index, str(_INDEX_FILE))
    _CHUNKS_FILE.write_text(json.dumps(_chunk_texts, ensure_ascii=False, indent=2), encoding="utf-8")
    _META_FILE.write_text(json.dumps(_metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("FAISS index persisted to: %s", index_dir)


def load_index(index_dir: Optional[pathlib.Path] = None) -> bool:
    """
    Load a previously persisted index from disk.

    Returns:
        True if successfully loaded, False if files are missing.
    """
    global _faiss_index, _chunk_texts, _metadata
    faiss = _import_faiss()

    idir = index_dir or _DEFAULT_INDEX_DIR
    idx_path = idir / "faiss.index"
    chunks_path = idir / "chunks.json"
    meta_path = idir / "metadata.json"

    if not (idx_path.exists() and chunks_path.exists() and meta_path.exists()):
        logger.info("No persisted FAISS index found at: %s", idir)
        return False

    _faiss_index = faiss.read_index(str(idx_path))
    _chunk_texts = json.loads(chunks_path.read_text(encoding="utf-8"))
    _metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    logger.info(
        "FAISS index loaded from disk: %d vectors", _faiss_index.ntotal
    )
    return True


def search(
    query_embedding: np.ndarray,
    top_k: int = 5,
) -> List[Tuple[str, Dict[str, Any], float]]:
    """
    Search the FAISS index for the *top_k* most similar chunks.

    Args:
        query_embedding: 1-D float32 vector (shape: (dim,)).
        top_k:           Number of results to return.

    Returns:
        List of (chunk_text, metadata_dict, score) tuples ordered by
        descending cosine similarity.

    Raises:
        RuntimeError: If the index has not been built or loaded yet.
    """
    if _faiss_index is None:
        raise RuntimeError(
            "FAISS index is not initialised. Call build_index() or load_index() first."
        )

    vec = query_embedding.reshape(1, -1).astype(np.float32)
    vec = _normalise(vec)

    k = min(top_k, _faiss_index.ntotal)
    scores, indices = _faiss_index.search(vec, k)  # type: ignore[attr-defined]

    results: List[Tuple[str, Dict[str, Any], float]] = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0:          # FAISS returns -1 for padding when k > ntotal
            continue
        results.append((_chunk_texts[idx], _metadata[idx], float(score)))

    return results


def is_index_ready() -> bool:
    """Return True if the index is initialised and non-empty."""
    return _faiss_index is not None and _faiss_index.ntotal > 0
