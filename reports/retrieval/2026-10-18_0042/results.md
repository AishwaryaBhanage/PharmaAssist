# Retrieval experiment, 2026-10-18 00:42

Direct hybrid search (dense + BM25, RRF k=60) on the 19 golden questions with PDF gold pages (Q20 has none; formulary rows aren't searchable text). No agent, no judge.

Recall@k counts gold pages covered by the top-k returned units (chunks, or parent sections). **Recall at matched tokens** gives every setup the same text budget as `sections_openai`'s top 10, so bigger units don't win just by returning more text. **Children R@10** counts only the pages of the matched children (the ranking alone, before parent expansion).

| Setup | Chunks (parents) | Embedder | Reranker | Recall@5 | Recall@10 | Recall at matched tokens | Children R@10 | Previously missed fixed (R@10 = 1) | Near-dup in top 5 | Same-page repeats in top 5 | Median tokens in top 5 / 10 | Build time | Embedding cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| D. `sections_openai` | 1962 (581) | text-embedding-3-large | – | 0.687 | 0.833 | 0.833 | 0.783 | Q01, Q03, Q05, Q16; improved: Q04, Q06, Q10, Q19 | 0% | 1% | 4681 / 9325 | 77.2 s | $0.068 |
| E. `sections_openai_rerank` | 1962 (581) | text-embedding-3-large | bge-reranker-base | 0.675 | 0.882 | 0.864 | 0.840 | Q01, Q03, Q04, Q05, Q16, Q19; improved: Q06, Q07, Q10 | 0% | 2% | 4806 / 9096 | 77.2 s | $0.068 |
| F0. `docling_norerank` | 1983 (589) | text-embedding-3-large | – | 0.744 | 0.820 | 0.820 | 0.757 | Q01, Q03, Q05, Q16; improved: Q04, Q06, Q07, Q10, Q19 | 0% | 4% | 4937 / 8999 | 31.7 s | $0.071 |
| F. `docling_sections` | 1983 (589) | text-embedding-3-large | bge-reranker-base | 0.729 | 0.842 | 0.851 | 0.777 | Q01, Q05, Q16, Q19; improved: Q03, Q04, Q06, Q07, Q10 | 1% | 2% | 4497 / 9440 | 31.7 s | $0.071 |

## Recall@10 per question

| ID | D | E | F0 | F |
|---|---|---|---|---|
| Q01 * | 1.00 | 1.00 | 1.00 | 1.00 |
| Q02 | 1.00 | 1.00 | 1.00 | 1.00 |
| Q03 * | 1.00 | 1.00 | 1.00 | 0.75 |
| Q04 * | 0.67 | 1.00 | 0.50 | 0.83 |
| Q05 * | 1.00 | 1.00 | 1.00 | 1.00 |
| Q06 * | 0.50 | 0.50 | 0.50 | 0.50 |
| Q07 * | 0.00 | 0.25 | 0.25 | 0.25 |
| Q08 | 1.00 | 1.00 | 1.00 | 1.00 |
| Q09 | 1.00 | 1.00 | 1.00 | 1.00 |
| Q10 * | 0.67 | 0.67 | 0.33 | 0.67 |
| Q11 | 1.00 | 1.00 | 1.00 | 1.00 |
| Q12 | 1.00 | 1.00 | 1.00 | 1.00 |
| Q13 | 1.00 | 1.00 | 1.00 | 0.67 |
| Q14 | 0.67 | 0.33 | 0.67 | 0.33 |
| Q15 | 1.00 | 1.00 | 1.00 | 1.00 |
| Q16 * | 1.00 | 1.00 | 1.00 | 1.00 |
| Q17 | 1.00 | 1.00 | 1.00 | 1.00 |
| Q18 | 1.00 | 1.00 | 1.00 | 1.00 |
| Q19 * | 0.33 | 1.00 | 0.33 | 1.00 |

\* previously missed by the structured agent run (gold never returned by any tool).
