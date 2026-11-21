# Retrieval experiment, 2026-10-18 00:43

Direct hybrid search (dense + BM25, RRF k=60) on the 8 golden questions with PDF gold pages (Q20 has none; formulary rows aren't searchable text). No agent, no judge.

Recall@k counts gold pages covered by the top-k returned units (chunks, or parent sections). **Recall at matched tokens** gives every setup the same text budget as `sections_openai`'s top 10, so bigger units don't win just by returning more text. **Children R@10** counts only the pages of the matched children (the ranking alone, before parent expansion).

| Setup | Chunks (parents) | Embedder | Reranker | Recall@5 | Recall@10 | Recall at matched tokens | Children R@10 | Previously missed fixed (R@10 = 1) | Near-dup in top 5 | Same-page repeats in top 5 | Median tokens in top 5 / 10 | Build time | Embedding cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| D. `sections_openai` | 1962 (581) | text-embedding-3-large | – | 0.646 | 0.875 | 0.875 | 0.792 | none | 0% | 2% | 4809 / 9969 | 77.2 s | $0.068 |
| E. `sections_openai_rerank` | 1962 (581) | text-embedding-3-large | bge-reranker-base | 0.750 | 0.875 | 0.875 | 0.792 | none | 0% | 2% | 4864 / 10576 | 77.2 s | $0.068 |
| F0. `docling_norerank` | 1983 (589) | text-embedding-3-large | – | 0.875 | 0.958 | 0.958 | 0.917 | none | 2% | 0% | 4731 / 9540 | 31.7 s | $0.071 |
| F. `docling_sections` | 1983 (589) | text-embedding-3-large | bge-reranker-base | 0.708 | 1.000 | 1.000 | 0.917 | none | 2% | 8% | 4684 / 9987 | 31.7 s | $0.071 |

## Recall@10 per question

| ID | D | E | F0 | F |
|---|---|---|---|---|
| V01 | 1.00 | 1.00 | 1.00 | 1.00 |
| V02 | 1.00 | 1.00 | 1.00 | 1.00 |
| V03 | 0.67 | 0.67 | 1.00 | 1.00 |
| V04 | 0.33 | 0.33 | 0.67 | 1.00 |
| V05 | 1.00 | 1.00 | 1.00 | 1.00 |
| V06 | 1.00 | 1.00 | 1.00 | 1.00 |
| V07 | 1.00 | 1.00 | 1.00 | 1.00 |
| V08 | 1.00 | 1.00 | 1.00 | 1.00 |

\* previously missed by the structured agent run (gold never returned by any tool).
