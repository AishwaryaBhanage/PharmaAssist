# Retrieval experiment, 2026-10-16 01:21

Direct hybrid search (dense + BM25, RRF k=60) on the 19 golden questions with PDF gold pages (Q20 has none; formulary rows aren't searchable text). No agent, no judge.

Recall@k counts gold pages covered by the top-k returned units (chunks, or parent sections). **Recall at matched tokens** gives every setup the same text budget as `sections_openai`'s top 10, so bigger units don't win just by returning more text. **Children R@10** counts only the pages of the matched children (the ranking alone, before parent expansion).

| Setup | Chunks (parents) | Embedder | Reranker | Recall@5 | Recall@10 | Recall at matched tokens | Children R@10 | Previously missed fixed (R@10 = 1) | Near-dup in top 5 | Same-page repeats in top 5 | Median tokens in top 5 / 10 | Build time | Embedding cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A. `baseline` | 1521 | bge-small-en-v1.5 | – | 0.552 | 0.646 | 0.838 | 0.646 | none | 0% | 13% | 1638 / 3272 | 70.4 s | $0.000 |
| B. `fixed_openai` | 1521 | text-embedding-3-large | – | 0.567 | 0.713 | 0.877 | 0.713 | Q05; improved: Q01, Q03, Q04 | 0% | 7% | 1588 / 3228 | 61.6 s | $0.055 |
| C. `sections_bge` | 1962 (581) | bge-small-en-v1.5 | – | 0.652 | 0.750 | 0.732 | 0.674 | Q01, Q05; improved: Q03, Q10 | 0% | 3% | 4176 / 8066 | 87.9 s | $0.000 |
| D. `sections_openai` | 1962 (581) | text-embedding-3-large | – | 0.687 | 0.833 | 0.833 | 0.783 | Q01, Q03, Q05, Q16; improved: Q10 | 0% | 1% | 4681 / 9325 | 77.2 s | $0.068 |
| E. `sections_openai_rerank` | 1962 (581) | text-embedding-3-large | bge-reranker-base | 0.675 | 0.882 | 0.864 | 0.840 | Q01, Q03, Q04, Q05, Q16, Q19; improved: Q10 | 0% | 2% | 4806 / 9096 | 77.2 s | $0.068 |

## Recall@10 per question

| ID | A | B | C | D | E |
|---|---|---|---|---|---|
| Q01 * | 0.60 | 0.80 | 1.00 | 1.00 | 1.00 |
| Q02 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| Q03 * | 0.50 | 0.75 | 0.75 | 1.00 | 1.00 |
| Q04 * | 0.67 | 0.83 | 0.67 | 0.67 | 1.00 |
| Q05 * | 0.50 | 1.00 | 1.00 | 1.00 | 1.00 |
| Q06 * | 0.75 | 0.75 | 0.25 | 0.50 | 0.50 |
| Q07 * | 0.25 | 0.25 | 0.25 | 0.00 | 0.25 |
| Q08 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| Q09 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| Q10 * | 0.00 | 0.00 | 0.67 | 0.67 | 0.67 |
| Q11 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| Q12 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| Q13 | 1.00 | 1.00 | 0.67 | 1.00 | 1.00 |
| Q14 | 0.67 | 0.33 | 0.67 | 0.67 | 0.33 |
| Q15 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| Q16 * | 0.50 | 0.50 | 0.00 | 1.00 | 1.00 |
| Q17 | 0.50 | 0.50 | 1.00 | 1.00 | 1.00 |
| Q18 | 0.00 | 0.50 | 1.00 | 1.00 | 1.00 |
| Q19 * | 0.33 | 0.33 | 0.33 | 0.33 | 1.00 |

\* previously missed by the structured agent run (gold never returned by any tool).

## Baseline: where the missed gold pages rank

Chunk ranks for the best chunk on each gold page missing from A's top 10. Fused = the hybrid ranking (top 100 only); dense and BM25 = each half's full ranking over 1,521 chunks.

| ID | Missed gold page | Fused rank | Dense rank | BM25 rank | Chunks on page |
|---|---|---|---|---|---|
| Q01 | va_dod_cpg_diabetes_2023:p58 | 23 | 19 | 68 | 3 |
| Q01 | va_pbm_t2dm_clinicians_guide:p12 | 13 | 7 | 21 | 2 |
| Q03 | va_pbm_bup_chronic_pain:p2 | 15 | 9 | 27 | 4 |
| Q03 | va_pbm_bup_oud:p2 | 12 | 1 | 21 | 4 |
| Q04 | cms_partd_dmp_guidance_2019:p1 | 27 | 52 | 10 | 2 |
| Q04 | cms_partd_dmp_guidance_2019:p5 | 11 | 9 | 7 | 3 |
| Q05 | ny_medicaid_pharmacy_policy:p18 | 17 | 58 | 8 | 3 |
| Q05 | ny_medicaid_pharmacy_policy:p19 | 13 | 22 | 16 | 2 |
| Q06 | va_pbm_t2dm_pharmacotherapy_2025:p12 | >100 | 400 | 534 | 2 |
| Q07 | va_dod_cpg_opioids_2022:p33 | 59 | 10 | 89 | 2 |
| Q07 | va_pbm_bup_oud:p3 | 13 | 22 | 18 | 2 |
| Q07 | va_pbm_bup_oud:p4 | 93 | 104 | 58 | 8 |
| Q10 | va_dod_cpg_opioids_2022:p33 | 50 | 8 | 22 | 2 |
| Q10 | va_pbm_bup_chronic_pain:p1 | 11 | 2 | 35 | 2 |
| Q10 | va_pbm_bup_chronic_pain:p2 | 15 | 18 | 29 | 4 |
| Q16 | ny_medicaid_pdl:p77 | >100 | 252 | 99 | 2 |
| Q19 | ny_medicaid_pdl:p34 | 52 | 493 | 25 | 1 |
| Q19 | ny_medicaid_pharmacy_policy:p41 | 29 | 13 | 171 | 3 |
