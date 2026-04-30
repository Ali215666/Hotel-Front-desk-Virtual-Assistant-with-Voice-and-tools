"""
RAG index builder script.

Run this once (or any time the document corpus changes) to:
  1. Generate all 50 hotel documents in data/docs/
  2. Chunk each document
  3. Embed every chunk with all-MiniLM-L6-v2
  4. Build and persist the FAISS index to data/index/

Usage (from the project root):
    python rag/build_index.py

The server will load the persisted index on startup and will NOT re-embed
unless the index files are missing or deleted.
"""

from __future__ import annotations

import logging
import pathlib
import sys
import time

# Ensure the project root is on sys.path so that relative imports work
# regardless of where the script is invoked from.
_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    t0 = time.perf_counter()

    # ── Step 1: Generate documents ────────────────────────────────────────
    logger.info("Step 1/4 — Generating hotel documents …")
    from rag.generate_docs import generate_documents
    docs_dir = _ROOT / "data" / "docs"
    generate_documents(str(docs_dir))

    # ── Step 2: Chunk documents ───────────────────────────────────────────
    logger.info("Step 2/4 — Chunking documents …")
    from rag.chunker import chunk_text

    doc_files = sorted(docs_dir.glob("doc_*.txt"))
    all_chunks: list[str] = []
    all_meta: list[dict] = []

    for doc_file in doc_files:
        doc_id = doc_file.stem
        text = doc_file.read_text(encoding="utf-8")
        chunks = chunk_text(text)
        for chunk_idx, chunk in enumerate(chunks):
            all_chunks.append(chunk)
            all_meta.append({"doc_id": doc_id, "chunk_id": chunk_idx})

    logger.info("  → %d total chunks from %d documents", len(all_chunks), len(doc_files))

    # ── Step 3: Embed chunks ──────────────────────────────────────────────
    logger.info("Step 3/4 — Embedding chunks with all-MiniLM-L6-v2 …")
    from rag.embeddings import embed_batch

    embeddings = embed_batch(all_chunks)
    logger.info("  → Embedding matrix shape: %s", embeddings.shape)

    # ── Step 4: Build and persist FAISS index ─────────────────────────────
    logger.info("Step 4/4 — Building FAISS index …")
    from rag import vector_store

    index_dir = _ROOT / "data" / "index"
    vector_store.build_index(all_chunks, embeddings, metadata=all_meta, persist=True, index_dir=index_dir)

    elapsed = time.perf_counter() - t0
    logger.info("RAG index built successfully in %.1f s", elapsed)
    logger.info("    Index location: %s", index_dir)


if __name__ == "__main__":
    main()
