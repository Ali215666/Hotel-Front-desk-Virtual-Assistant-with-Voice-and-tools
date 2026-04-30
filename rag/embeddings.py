"""
STEP 3 — Embedding functions using sentence-transformers.

Model: all-MiniLM-L6-v2  (fully local, CPU-friendly, ~80 MB)

The model is loaded once as a module-level singleton so multiple callers
share the same instance and avoid repeated disk I/O.
"""

from __future__ import annotations

import logging
from typing import List

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy singleton — loaded on first call, never reloaded.
# ---------------------------------------------------------------------------
_model = None
_MODEL_NAME = "all-MiniLM-L6-v2"


def _get_model():
    """Return the loaded SentenceTransformer model, loading it if necessary."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is not installed. "
                "Run: pip install sentence-transformers"
            ) from exc

        logger.info("Loading embedding model: %s …", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
        logger.info("Embedding model loaded.")
    return _model


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_embedding(text: str) -> np.ndarray:
    """
    Compute the embedding vector for a single piece of text.

    Args:
        text: Input string to embed.

    Returns:
        np.ndarray: 1-D float32 array of shape (384,).
    """
    if not text or not text.strip():
        raise ValueError("Cannot embed an empty string.")

    model = _get_model()
    # encode() returns a 2-D array; squeeze to 1-D for a single input.
    vector: np.ndarray = model.encode([text], convert_to_numpy=True)[0]
    return vector.astype(np.float32)


def embed_batch(texts: List[str]) -> np.ndarray:
    """
    Compute embeddings for a list of texts in a single batched call.

    Args:
        texts: List of input strings.

    Returns:
        np.ndarray: 2-D float32 array of shape (len(texts), 384).
                    Rows correspond to input texts in order.

    Raises:
        ValueError: If *texts* is empty.
    """
    if not texts:
        raise ValueError("texts list must not be empty.")

    model = _get_model()
    vectors: np.ndarray = model.encode(
        texts,
        convert_to_numpy=True,
        batch_size=32,
        show_progress_bar=False,
    )
    return vectors.astype(np.float32)
