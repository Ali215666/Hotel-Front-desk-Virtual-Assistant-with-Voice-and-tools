"""
Hotel RAG Evaluation Suite
==========================
Evaluates the hotel's FAISS-based RAG system across 25 realistic FAQ queries.

What this script measures
--------------------------
1. Retrieval quality   — Precision@3, Recall@3, MRR
2. Answer generation   — Ollama (llama3) answers grounded in retrieved chunks
3. Answer faithfulness — RAGAS Faithfulness metric

System layout
-------------
  data/
    docs/       doc_001.txt … doc_051.txt   (51 hotel policy documents)
    index/
      faiss.index    FAISS IndexFlatIP
      chunks.json    flat list of chunk strings  (index == chunk_id)
      metadata.json  list of {doc_id, chunk_id} dicts

  rag/
    retriever.py    retrieve(query, top_k) -> List[str]
    vector_store.py search() returns (text, meta, score) triples
    embeddings.py   all-MiniLM-L6-v2

Usage
-----
  python tests/test_rag_evals.py

Dependencies
------------
  pip install ragas datasets requests faiss-cpu sentence-transformers
"""

from __future__ import annotations

import json
import logging
import pathlib
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("rag_eval")

# ── Path bootstrap — make project root importable ────────────────────────────
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ── Paths ─────────────────────────────────────────────────────────────────────
INDEX_DIR   = _REPO_ROOT / "data" / "index"
FAISS_PATH  = INDEX_DIR / "faiss.index"
CHUNKS_PATH = INDEX_DIR / "chunks.json"
META_PATH   = INDEX_DIR / "metadata.json"
REPORT_DIR  = _REPO_ROOT / "eval_reports"
REPORT_PATH = REPORT_DIR / "rag_report.md"

# ── Ollama ────────────────────────────────────────────────────────────────────
OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:3b"
OLLAMA_TIMEOUT = 120        # seconds per generation call
OLLAMA_MAX_RETRIES = 3

# ── Retrieval ─────────────────────────────────────────────────────────────────
TOP_K = 3


# ══════════════════════════════════════════════════════════════════════════════
# 1.  GROUND TRUTH
#     Maps each query to a list of chunk_ids (0-based position in chunks.json)
#     that contain relevant information.
#
#     chunks.json layout (0-indexed):
#       0  Cancellation Policy          14  Early Booking Discount
#       1  No-Show Policy               15  Group Booking Policy
#       2  Refund Policy                16  Corporate Booking Policy
#       3  Pet Policy                   17  Online Booking Terms
#       4  Smoking Policy               18  Waitlist Policy
#       5  Guest Conduct Policy         19  Promotional Rate Rules
#       6  Visitor Policy               20  Reservation Hold Policy
#       7  Noise Policy                 21  Standard Check-in Time
#       8  Damage Policy                22  Standard Check-out Time
#       9  Children Policy              23  Late Check-out Policy
#      10  Reservation Process          24  Early Check-in Policy
#      11  Booking Modification         25  Express Check-in
#      12  Peak Season Booking          26  Express Check-out
#      13  Early Booking Discount       27  Check-in Documentation
#      28  Room Assignment Policy       39  Room Service
#      29  Accepted Payment Methods     40  Parking Facilities
#      30  Security Deposit             41  FAQ: Is breakfast included?
#      31  Billing and Invoicing        42  FAQ: Is parking free?
#      32  Incidental Charges           43  FAQ: Are pets allowed?
#      33  Advance Payment              44  FAQ: Cancellation deadline?
#      34  Currency Exchange            45  FAQ: Airport shuttle?
#      35  Refund Timeline              46  FAQ: Early check-in?
#      36  Wi-Fi Services               47  FAQ: Restaurant?
#      37  Fitness Centre               48  FAQ: Gym open 24hrs?
#      38  Swimming Pool                49  FAQ: Wi-Fi?
#                                       50  FAQ: Late check-out fee?
# ══════════════════════════════════════════════════════════════════════════════

GROUND_TRUTH: Dict[str, List[int]] = {
    # Check-out time
    "What time is check-out?": [21, 22, 49],
    # Pool availability
    "Do you have a swimming pool?": [37],
    # Cancellation policy
    "What is the cancellation policy?": [0, 43],
    # Breakfast inclusion
    "Is breakfast included in the room rate?": [40],
    # Room types
    "What room types are available?": [27],
    # Parking
    "Is parking available at the hotel?": [39, 41],
    # Pet policy
    "Are pets allowed at the hotel?": [3, 42],
    # Gym hours
    "What are the gym opening hours?": [36, 47],
    # Wi-Fi
    "How do I connect to the hotel Wi-Fi?": [35, 48],
    # Early check-in
    "Can I check in early?": [23, 45],
    # Late check-out
    "Is late check-out available?": [22, 49],
    # Airport shuttle
    "Do you offer an airport shuttle service?": [44],
    # Smoking policy
    "What is the smoking policy?": [4],
    # Restaurant hours
    "What are the restaurant opening hours?": [46],
    # Laundry service
    "Do you provide laundry or dry-cleaning services?": [31],
    # Room service hours
    "Is room service available and what are the hours?": [38],
    # Conference room booking
    "How can I book a conference room?": [14],
    # Pool hours
    "What are the swimming pool opening hours?": [37],
    # Kids policy
    "What is the policy for children staying at the hotel?": [9],
    # Noise policy
    "What are the quiet hours at the hotel?": [7],
    # Minibar policy
    "Are there minibar charges if I use it?": [31],
    # Payment methods
    "What payment methods does the hotel accept?": [28],
}

# Ordered list for iteration (preserves insertion order — Python 3.7+)
QUERIES: List[str] = list(GROUND_TRUTH.keys())


# ══════════════════════════════════════════════════════════════════════════════
# 2.  RETRIEVER WRAPPER
#     Uses rag.vector_store directly so we get chunk_id from metadata —
#     never relies on list.index() which is unreliable with duplicate texts.
# ══════════════════════════════════════════════════════════════════════════════

def load_rag_system() -> bool:
    """
    Load the FAISS index and chunk data into the vector_store singleton.

    Returns:
        True if the index loaded successfully, False otherwise.
    """
    # Validate required files exist before attempting import.
    for label, path in [
        ("FAISS index",  FAISS_PATH),
        ("chunks.json",  CHUNKS_PATH),
        ("metadata.json", META_PATH),
    ]:
        if not path.exists():
            logger.error("Missing required file — %s: %s", label, path)
            return False

    try:
        from rag import vector_store
        ok = vector_store.load_index(INDEX_DIR)
        if not ok:
            logger.error("vector_store.load_index() returned False.")
            return False
        logger.info(
            "RAG system loaded — %d vectors in index.", vector_store._faiss_index.ntotal
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to load RAG system: %s", exc, exc_info=True)
        return False


def retrieve_with_ids(query: str, k: int = TOP_K) -> List[Dict[str, Any]]:
    """
    Retrieve the top-k chunks for *query* and return their **global** position
    in the FAISS index as chunk_id.

    Root cause of the old bug
    -------------------------
    metadata.json stores {"doc_id": "doc_XXX", "chunk_id": 0} for every entry
    because each document produces exactly one chunk, so the *per-document*
    chunk index is always 0.  Using meta["chunk_id"] would always yield 0.

    Fix
    ---
    We call faiss.search() directly (bypassing vector_store.search()) so we
    get the raw FAISS integer index — that IS the global sequential position
    in chunks.json and is identical to the chunk_id used in GROUND_TRUTH.

    Returns:
        List of dicts:  {"chunk_id": int, "text": str, "score": float}
        Empty list on any failure.
    """
    try:
        import numpy as np
        from rag import vector_store
        from rag.embeddings import get_embedding

        if not vector_store.is_index_ready():
            logger.warning("Index not ready — returning empty results.")
            return []

        # Embed and L2-normalise the query (index uses cosine / inner-product).
        query_vec = get_embedding(query).reshape(1, -1).astype(np.float32)
        norm = np.linalg.norm(query_vec, axis=1, keepdims=True)
        query_vec = (query_vec / np.where(norm == 0, 1.0, norm)).astype(np.float32)

        # Search — scores[0] and indices[0] are parallel arrays of length k.
        k_actual = min(k, vector_store._faiss_index.ntotal)
        scores, indices = vector_store._faiss_index.search(query_vec, k_actual)

        results: List[Dict[str, Any]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:          # FAISS pads with -1 when k > ntotal
                continue
            results.append({
                # idx is the global sequential position — same numbering as
                # chunks.json and our GROUND_TRUTH annotations.
                "chunk_id": int(idx),
                "text":     vector_store._chunk_texts[idx],
                "score":    float(score),
            })

        return results

    except Exception as exc:  # noqa: BLE001
        logger.error("Retrieval failed for query '%s': %s", query[:60], exc)
        return []


# ══════════════════════════════════════════════════════════════════════════════
# 3.  RETRIEVAL METRICS
# ══════════════════════════════════════════════════════════════════════════════

def precision_at_k(
    retrieved_ids: List[int],
    relevant_ids: List[int],
    k: int = TOP_K,
) -> float:
    """
    Precision@k = |relevant ∩ retrieved[:k]| / k

    If relevant_ids is empty the query has no known relevant chunks;
    we return 0.0 so it does not artificially inflate the metric.
    """
    if not relevant_ids:
        return 0.0
    retrieved_k = retrieved_ids[:k]
    hits = sum(1 for rid in retrieved_k if rid in relevant_ids)
    return hits / k


def recall_at_k(
    retrieved_ids: List[int],
    relevant_ids: List[int],
    k: int = TOP_K,
) -> float:
    """
    Recall@k = |relevant ∩ retrieved[:k]| / |relevant|

    Returns 0.0 when relevant_ids is empty (no ground truth = cannot recall).
    """
    if not relevant_ids:
        return 0.0
    retrieved_k = retrieved_ids[:k]
    hits = sum(1 for rid in retrieved_k if rid in relevant_ids)
    return hits / len(relevant_ids)


def reciprocal_rank(
    retrieved_ids: List[int],
    relevant_ids: List[int],
) -> float:
    """
    MRR component: 1 / rank_of_first_relevant_result.
    Returns 0.0 if no relevant chunk is found or relevant_ids is empty.
    """
    if not relevant_ids:
        return 0.0
    for rank, rid in enumerate(retrieved_ids, start=1):
        if rid in relevant_ids:
            return 1.0 / rank
    return 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 4.  OLLAMA ANSWER GENERATION
# ══════════════════════════════════════════════════════════════════════════════

ANSWER_PROMPT_TEMPLATE = """\
You are a hotel assistant.
Answer ONLY using the provided context.
If the answer is not contained in the context, say "I don't know."

Context:
{context}

Question:
{question}

Answer:"""


def generate_answer(question: str, context_chunks: List[str]) -> str:
    """
    Call the local Ollama API to generate an answer grounded in *context_chunks*.

    Retries up to OLLAMA_MAX_RETRIES times on connection or server errors.

    Args:
        question:       The user's question.
        context_chunks: Retrieved text chunks to use as context.

    Returns:
        The generated answer string, or an error sentinel.
    """
    context = "\n\n".join(context_chunks) if context_chunks else "(no context retrieved)"
    prompt = ANSWER_PROMPT_TEMPLATE.format(context=context, question=question)

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }

    for attempt in range(1, OLLAMA_MAX_RETRIES + 1):
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            answer = data.get("response", "").strip()
            return answer if answer else "I don't know."

        except requests.exceptions.ConnectionError:
            logger.error(
                "Ollama not reachable at %s (attempt %d/%d). "
                "Ensure Ollama is running: `ollama serve`",
                OLLAMA_URL, attempt, OLLAMA_MAX_RETRIES,
            )
        except requests.exceptions.Timeout:
            logger.warning(
                "Ollama generation timed out after %ds (attempt %d/%d).",
                OLLAMA_TIMEOUT, attempt, OLLAMA_MAX_RETRIES,
            )
        except requests.exceptions.HTTPError as exc:
            logger.error("Ollama HTTP error: %s (attempt %d/%d)", exc, attempt, OLLAMA_MAX_RETRIES)
        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected Ollama error: %s (attempt %d/%d)", exc, attempt, OLLAMA_MAX_RETRIES)

        if attempt < OLLAMA_MAX_RETRIES:
            sleep_secs = 2 ** attempt   # 2s, 4s, 8s
            logger.info("Retrying in %ds …", sleep_secs)
            time.sleep(sleep_secs)

    return "[GENERATION FAILED — Ollama unavailable]"


# ══════════════════════════════════════════════════════════════════════════════
# 5.  RAGAS FAITHFULNESS EVALUATION
# ══════════════════════════════════════════════════════════════════════════════

def run_ragas_faithfulness(
    questions: List[str],
    answers: List[str],
    contexts: List[List[str]],
) -> Tuple[List[float], float]:
    """
    Evaluate faithfulness of answers with respect to their retrieved contexts
    using the RAGAS library.

    Builds a single HuggingFace Dataset in the format RAGAS expects:
        {"question": [...], "answer": [...], "contexts": [[...], [...]]}

    Args:
        questions: List of user questions.
        answers:   List of generated answers (parallel with questions).
        contexts:  List of context-chunk lists (parallel with questions).

    Returns:
        (per_query_scores, avg_score)
        per_query_scores: float per question (NaN on evaluation failure)
        avg_score: mean faithfulness across all questions
    """
    try:
        from datasets import Dataset  # type: ignore
        from ragas import evaluate    # type: ignore
        from ragas.metrics import Faithfulness  # type: ignore
    except ImportError as exc:
        logger.error(
            "RAGAS or HuggingFace datasets not installed: %s\n"
            "Run: pip install ragas datasets",
            exc,
        )
        nan = float("nan")
        return [nan] * len(questions), nan

    logger.info("Building RAGAS dataset with %d samples …", len(questions))

    try:
        dataset = Dataset.from_dict({
            "question": questions,
            "answer": answers,
            "contexts": contexts,
        })
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to build RAGAS Dataset: %s", exc)
        nan = float("nan")
        return [nan] * len(questions), nan

    try:
        from langchain_community.chat_models import ChatOllama
    except ImportError as exc:
        logger.error(
            "langchain-community is not installed but required for Ollama RAGAS eval.\n"
            "Run: pip install langchain-community langchain",
            exc_info=True,
        )
        nan = float("nan")
        return [nan] * len(questions), nan

    try:
        logger.info("Configuring Ollama LLM for RAGAS evaluation …")
        judge_llm = ChatOllama(
            model=OLLAMA_MODEL,
            base_url="http://localhost:11434",
            temperature=0.0
        )
        
        # Depending on RAGAS version, it might be `faithfulness` or `Faithfulness()`
        try:
            from ragas.metrics import faithfulness
            metric = faithfulness
        except ImportError:
            from ragas.metrics import Faithfulness
            metric = Faithfulness()

        logger.info("Running RAGAS Faithfulness evaluation (this may take a while) …")
        result = evaluate(
            dataset,
            metrics=[metric],
            llm=judge_llm
        )

        # Extract per-query faithfulness scores from the result DataFrame.
        try:
            df = result.to_pandas()
            # Handle possible column name variations depending on RAGAS version
            col_name = "faithfulness" if "faithfulness" in df.columns else df.columns[-1]
            per_query: List[float] = df[col_name].tolist()
        except Exception as df_exc:  # noqa: BLE001
            logger.warning("Failed to extract per-query scores via to_pandas(): %s", df_exc, exc_info=True)
            # Fallback: use the aggregate score for all queries.
            try:
                agg = float(result["faithfulness"])
                per_query = [agg] * len(questions)
            except Exception as agg_exc:
                logger.error("Could not extract any faithfulness score: %s", agg_exc, exc_info=True)
                per_query = [float("nan")] * len(questions)

        valid = [s for s in per_query if not (s != s)]  # filter NaN
        avg = sum(valid) / len(valid) if valid else float("nan")
        return per_query, avg

    except Exception as exc:  # noqa: BLE001
        logger.error("RAGAS evaluate() failed: %s", exc, exc_info=True)
        nan = float("nan")
        return [nan] * len(questions), nan


# ══════════════════════════════════════════════════════════════════════════════
# 6.  REPORT GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

def _fmt(val: float, decimals: int = 3) -> str:
    """Format a float; show '—' for NaN."""
    if val != val:  # NaN check
        return "—"
    return f"{val:.{decimals}f}"


def generate_report(rows: List[Dict[str, Any]]) -> None:
    """
    Write eval_reports/rag_report.md containing:
      - System summary (averages)
      - Per-query metrics table with ⚠️ AT RISK flags for faithfulness < 0.6
    """
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # Compute aggregates (skip NaN for faithfulness)
    n = len(rows)
    avg_p3  = sum(r["precision_at_3"] for r in rows) / n if n else 0.0
    avg_r3  = sum(r["recall_at_3"]    for r in rows) / n if n else 0.0
    avg_mrr = sum(r["mrr"]            for r in rows) / n if n else 0.0

    faith_vals = [r["faithfulness"] for r in rows if r["faithfulness"] == r["faithfulness"]]
    avg_faith  = sum(faith_vals) / len(faith_vals) if faith_vals else float("nan")

    lines = [
        "# Hotel RAG Evaluation Report",
        "",
        f"**Queries evaluated:** {n}  ",
        f"**Retriever:** FAISS IndexFlatIP + all-MiniLM-L6-v2  ",
        f"**Generator:** Ollama `{OLLAMA_MODEL}`  ",
        f"**k (top-k):** {TOP_K}  ",
        "",
        "## Aggregate Metrics",
        "",
        "| Metric | Score |",
        "|--------|------:|",
        f"| Average Precision@{TOP_K}  | {_fmt(avg_p3)} |",
        f"| Average Recall@{TOP_K}     | {_fmt(avg_r3)} |",
        f"| Average MRR               | {_fmt(avg_mrr)} |",
        f"| Average Faithfulness      | {_fmt(avg_faith)} |",
        "",
        "---",
        "",
        "## Per-Query Metrics",
        "",
        "> ⚠️ **AT RISK** = faithfulness < 0.6",
        "",
        f"| # | Query | P@{TOP_K} | R@{TOP_K} | MRR | Faithfulness | Flag |",
        f"|---|-------|:-----:|:-----:|:---:|:------------:|------|",
    ]

    for i, r in enumerate(rows, start=1):
        faith = r["faithfulness"]
        flag  = "⚠️ AT RISK" if faith == faith and faith < 0.6 else "✅ OK"
        q_short = r["query"][:55] + ("…" if len(r["query"]) > 55 else "")
        lines.append(
            f"| {i:02d} | {q_short} "
            f"| {_fmt(r['precision_at_3'], 2)} "
            f"| {_fmt(r['recall_at_3'], 2)} "
            f"| {_fmt(r['mrr'], 2)} "
            f"| {_fmt(faith, 2)} "
            f"| {flag} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Retrieved Chunk IDs per Query",
        "",
        "| # | Query | Retrieved IDs | Relevant IDs |",
        "|---|-------|:-------------:|:------------:|",
    ]

    for i, r in enumerate(rows, start=1):
        retrieved = ", ".join(map(str, r["retrieved_ids"])) or "—"
        relevant  = ", ".join(map(str, GROUND_TRUTH.get(r["query"], []))) or "—"
        q_short   = r["query"][:55] + ("…" if len(r["query"]) > 55 else "")
        lines.append(f"| {i:02d} | {q_short} | {retrieved} | {relevant} |")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Report written to: %s", REPORT_PATH)


# ══════════════════════════════════════════════════════════════════════════════
# 7.  MAIN EVALUATION LOOP
# ══════════════════════════════════════════════════════════════════════════════

def run_evaluation() -> None:
    """
    End-to-end evaluation pipeline:
      1. Load RAG system
      2. For each query: retrieve → compute metrics → generate answer
      3. Batch RAGAS faithfulness
      4. Write report
    """
    print("\n" + "=" * 65)
    print("  Hotel RAG Evaluation Suite")
    print("=" * 65)

    # ── 1. Load index ─────────────────────────────────────────────────────────
    print("\n[SETUP] Loading FAISS index ...")
    if not load_rag_system():
        print(
            "\n[ERROR] Could not load RAG system. "
            "Ensure the index has been built:\n"
            "  python rag/build_index.py\n"
        )
        sys.exit(1)
    print("[SETUP] Index loaded successfully.\n")

    total = len(QUERIES)
    rows: List[Dict[str, Any]] = []
    all_contexts: List[List[str]] = []
    all_answers:  List[str] = []

    # ── 2. Per-query retrieval + generation ───────────────────────────────────
    for idx, query in enumerate(QUERIES, start=1):
        print(f"[{idx:02d}/{total}] {query}")

        # --- Retrieval -------------------------------------------------------
        hits = retrieve_with_ids(query, k=TOP_K)

        if not hits:
            logger.warning("  No chunks retrieved for query %02d.", idx)

        retrieved_ids: List[int] = [h["chunk_id"] for h in hits]
        context_texts: List[str] = [h["text"] for h in hits]
        relevant_ids:  List[int] = GROUND_TRUTH.get(query, [])

        # --- Metrics ---------------------------------------------------------
        p3  = precision_at_k(retrieved_ids, relevant_ids)
        r3  = recall_at_k(retrieved_ids, relevant_ids)
        mrr = reciprocal_rank(retrieved_ids, relevant_ids)

        print(
            f"         Retrieved IDs : {retrieved_ids}   "
            f"Relevant IDs: {relevant_ids}"
        )
        print(f"         P@{TOP_K}={p3:.2f}  R@{TOP_K}={r3:.2f}  MRR={mrr:.2f}")

        # --- Generation ------------------------------------------------------
        print(f"         Generating answer via Ollama ({OLLAMA_MODEL}) …")
        answer = generate_answer(query, context_texts)
        truncated = answer[:100].replace("\n", " ") + ("…" if len(answer) > 100 else "")
        print(f"         Answer: {truncated}\n")

        rows.append({
            "query":         query,
            "retrieved_ids": retrieved_ids,
            "precision_at_3": p3,
            "recall_at_3":   r3,
            "mrr":           mrr,
            "faithfulness":  float("nan"),  # filled in after RAGAS batch
            "answer":        answer,
        })
        all_contexts.append(context_texts)
        all_answers.append(answer)

    # ── 3. RAGAS faithfulness batch ───────────────────────────────────────────
    print("\n" + "-" * 65)
    print("[RAGAS] Running faithfulness evaluation ...")
    print("-" * 65)

    per_query_faith, avg_faith = run_ragas_faithfulness(
        questions=QUERIES,
        answers=all_answers,
        contexts=all_contexts,
    )

    for row, faith in zip(rows, per_query_faith):
        row["faithfulness"] = faith

    # ── 4. Report ─────────────────────────────────────────────────────────────
    generate_report(rows)

    # ── 5. Console summary ────────────────────────────────────────────────────
    n = len(rows)
    avg_p3  = sum(r["precision_at_3"] for r in rows) / n
    avg_r3  = sum(r["recall_at_3"]    for r in rows) / n
    avg_mrr = sum(r["mrr"]            for r in rows) / n

    print("\n" + "=" * 65)
    print("  FINAL SUMMARY")
    print("=" * 65)
    print(f"  Queries evaluated : {n}")
    print(f"  Avg Precision@{TOP_K}  : {avg_p3:.3f}")
    print(f"  Avg Recall@{TOP_K}     : {avg_r3:.3f}")
    print(f"  Avg MRR           : {avg_mrr:.3f}")
    print(f"  Avg Faithfulness  : {_fmt(avg_faith)}")
    print("=" * 65)

    at_risk = [
        r["query"] for r in rows
        if r["faithfulness"] == r["faithfulness"] and r["faithfulness"] < 0.6
    ]
    if at_risk:
        print(f"\n  [!] {len(at_risk)} AT RISK queries (faithfulness < 0.6):")
        for q in at_risk:
            print(f"     - {q}")
    else:
        print("\n  [OK] All queries passed faithfulness threshold (>= 0.6)")

    print(f"\n[DONE] Report -> {REPORT_PATH}\n")


if __name__ == "__main__":
    run_evaluation()
