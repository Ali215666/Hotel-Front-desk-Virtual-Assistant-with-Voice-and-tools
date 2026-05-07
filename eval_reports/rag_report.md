# Hotel RAG Evaluation Report

**Queries evaluated:** 22  
**Retriever:** FAISS IndexFlatIP + all-MiniLM-L6-v2  
**Generator:** Ollama `qwen2.5:3b`  
**k (top-k):** 3  

## Aggregate Metrics

| Metric | Score |
|--------|------:|
| Average Precision@3  | 0.455 |
| Average Recall@3     | 0.985 |
| Average MRR               | 0.977 |
| Average Faithfulness      | 0.750 |

---

## Per-Query Metrics

> ⚠️ **AT RISK** = faithfulness < 0.6

| # | Query | P@3 | R@3 | MRR | Faithfulness | Flag |
|---|-------|:-----:|:-----:|:---:|:------------:|------|
| 01 | What time is check-out? | 0.67 | 0.67 | 1.00 | — | ✅ OK |
| 02 | Do you have a swimming pool? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 03 | What is the cancellation policy? | 0.67 | 1.00 | 1.00 | — | ✅ OK |
| 04 | Is breakfast included in the room rate? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 05 | What room types are available? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 06 | Is parking available at the hotel? | 0.67 | 1.00 | 1.00 | — | ✅ OK |
| 07 | Are pets allowed at the hotel? | 0.67 | 1.00 | 1.00 | — | ✅ OK |
| 08 | What are the gym opening hours? | 0.67 | 1.00 | 1.00 | — | ✅ OK |
| 09 | How do I connect to the hotel Wi-Fi? | 0.67 | 1.00 | 1.00 | — | ✅ OK |
| 10 | Can I check in early? | 0.67 | 1.00 | 1.00 | — | ✅ OK |
| 11 | Is late check-out available? | 0.67 | 1.00 | 1.00 | — | ✅ OK |
| 12 | Do you offer an airport shuttle service? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 13 | What is the smoking policy? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 14 | What are the restaurant opening hours? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 15 | Do you provide laundry or dry-cleaning services? | 0.33 | 1.00 | 0.50 | — | ✅ OK |
| 16 | Is room service available and what are the hours? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 17 | How can I book a conference room? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 18 | What are the swimming pool opening hours? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 19 | What is the policy for children staying at the hotel? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 20 | What are the quiet hours at the hotel? | 0.33 | 1.00 | 1.00 | 0.75 | ✅ OK |
| 21 | Are there minibar charges if I use it? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 22 | What payment methods does the hotel accept? | 0.33 | 1.00 | 1.00 | — | ✅ OK |

---

## Retrieved Chunk IDs per Query

| # | Query | Retrieved IDs | Relevant IDs |
|---|-------|:-------------:|:------------:|
| 01 | What time is check-out? | 21, 22, 20 | 21, 22, 49 |
| 02 | Do you have a swimming pool? | 37, 36, 46 | 37 |
| 03 | What is the cancellation policy? | 0, 43, 19 | 0, 43 |
| 04 | Is breakfast included in the room rate? | 40, 46, 38 | 40 |
| 05 | What room types are available? | 27, 38, 35 | 27 |
| 06 | Is parking available at the hotel? | 39, 41, 46 | 39, 41 |
| 07 | Are pets allowed at the hotel? | 3, 42, 5 | 3, 42 |
| 08 | What are the gym opening hours? | 47, 36, 46 | 36, 47 |
| 09 | How do I connect to the hotel Wi-Fi? | 48, 35, 46 | 35, 48 |
| 10 | Can I check in early? | 45, 23, 20 | 23, 45 |
| 11 | Is late check-out available? | 22, 49, 45 | 22, 49 |
| 12 | Do you offer an airport shuttle service? | 44, 35, 41 | 44 |
| 13 | What is the smoking policy? | 4, 9, 14 | 4 |
| 14 | What are the restaurant opening hours? | 46, 47, 21 | 46 |
| 15 | Do you provide laundry or dry-cleaning services? | 36, 31, 9 | 31 |
| 16 | Is room service available and what are the hours? | 38, 35, 27 | 38 |
| 17 | How can I book a conference room? | 14, 27, 35 | 14 |
| 18 | What are the swimming pool opening hours? | 37, 47, 46 | 37 |
| 19 | What is the policy for children staying at the hotel? | 9, 5, 3 | 9 |
| 20 | What are the quiet hours at the hotel? | 7, 46, 6 | 7 |
| 21 | Are there minibar charges if I use it? | 31, 41, 39 | 31 |
| 22 | What payment methods does the hotel accept? | 28, 32, 29 | 28 |