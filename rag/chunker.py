"""
STEP 2 — Text chunker with overlapping windows.

Splits a document into overlapping character-level chunks so that context
is preserved across chunk boundaries when retrieved.
"""

from typing import List


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 80) -> List[str]:
    """
    Split *text* into overlapping chunks of at most *chunk_size* characters.

    The overlap ensures that sentences split across a boundary appear in both
    the preceding and following chunk, preventing loss of context at edges.

    Args:
        text:       Input text to split.
        chunk_size: Maximum characters per chunk (default 500).
        overlap:    Number of overlapping characters between consecutive
                    chunks (default 80).  Must be smaller than chunk_size.

    Returns:
        List[str]: Ordered list of text chunks.  Empty list if *text* is
        empty or whitespace-only.

    Raises:
        ValueError: If overlap >= chunk_size.
    """
    if overlap >= chunk_size:
        raise ValueError(
            f"overlap ({overlap}) must be strictly less than chunk_size ({chunk_size})."
        )

    text = text.strip()
    if not text:
        return []

    # If the whole text fits in one chunk, return it as-is.
    if len(text) <= chunk_size:
        return [text]

    chunks: List[str] = []
    start = 0
    step = chunk_size - overlap  # how far to advance the window each iteration

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]

        # Try to break at the last whitespace within the chunk to avoid
        # mid-word splits when possible.
        if end < len(text):
            last_space = chunk.rfind(" ")
            if last_space > overlap:          # keep at least the overlap portion
                chunk = chunk[:last_space]
                end = start + last_space

        chunks.append(chunk.strip())
        start += step

        # Prevent an infinite loop on degenerate inputs.
        if step <= 0:
            break

    # Filter out any empty chunks produced by whitespace trimming.
    return [c for c in chunks if c]
