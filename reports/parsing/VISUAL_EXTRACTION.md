# Tables, images and flowcharts: parser choice, extraction checks and evaluation

Date: 2026-10-17/18. Corpus: the 10 catalog PDFs (569 pages); the VA formulary spreadsheet is unchanged
(structured lookup). Setup names are from `config.yaml`: **E** `sections_rerank_structured` (previous
parser: PyMuPDF text + pdfplumber tables, images dropped) and **F** `docling_rerank_structured` (this
work). Everything else (chunk sizes, embedder, BM25 + RRF, reranker, agent, judge) is identical.

## 1. Parser choice

**Mistral OCR was not evaluated**: no Mistral API key was available, and the decision was made to
use Docling. This is a gap, not a finding about Mistral OCR.

Docling 2.140.0 (`PdfPipelineOptions`: TableFormer accurate mode with cell matching, OCR on bitmap
regions, picture classification, picture images at 2×) was run on representative pages first
(the bake-off pages: the five algorithm pages, recommendation tables, NY PDL tables, image-heavy
PBM guide pages, a bar chart, plain text; the per-page Docling outputs were not kept):

| What | Docling result | Checked against the page |
|---|---|---|
| Recommendation table, diabetes CPG p25 | 6 columns, header row detected, row/column alignment correct, merged cells expanded | Rotated sub-topic "Screening for Comorbidities" read as "for Comorbidities"; the merged "Topic" cell (whole page) recognised for only 3 rows, now filled down by the chunker |
| Opioid flowcharts p25–27 | Detected as pictures, classified `flow_chart` (0.98–1.0), box text OCR'd | OCR text is an unordered bag: **no arrows, branch labels or outcomes** |
| Diabetes flowcharts p21–22 | **Not detected at all**; only the module title and abbreviations survived | A silent drop of a full-page raster flowchart |
| Opioid flowchart p26 | Detected, but cropped from box 20: boxes 18–19 read as loose text | The embedded image covers boxes 18–30 |
| Icons, logos, cover photos (PBM guides, NY manual) | Classified `icon`/`logo`/`photograph` | Correct for the samples viewed |
| Bar chart, pharmacotherapy p5 | `bar_chart` 0.98; OCR finds the numbers | Numbers without their series |

**Choice: Docling for layout, text, tables and picture detection/classification, plus targeted
vision extraction** for non-decorative figures, with three safeguards Docling alone lacks:

1. Every embedded PDF image is inventoried from the PDF itself; images Docling missed become figures
   (this recovers diabetes p21–22).
2. A Docling flow_chart picture lying inside a larger embedded image is re-cropped to the whole image
   (this recovers opioid boxes 18–19).
3. Flowcharts and charts are sent once to a vision model (`claude-opus-5-5`, JSON-schema output),
   which records numbered boxes, directed labelled edges, chart series, and anything unreadable.

Docling is the simplest option that preserves table structure locally with no per-page cost; it
can't interpret diagram relationships, so vision is used only where needed (50 of 207 images).

## 2. What was extracted

`PARSE_REPORT.json`, `FIGURES.json` (every image, its decision and reason, checks, status, cost).

- Parse: 569 pages in 637 s locally (cached by source SHA-256 + parser options; a rebuild with an
  unchanged corpus re-parses nothing).
- Images: 207 found. 157 decorative (Docling class logo/icon/…, <2% of the page, or judged decorative
  by the vision model, with the reason recorded); 50 indexed: 17 flowcharts, 5 charts, 6 diagrams,
  16 text images, 4 photos, 2 table images. Vision cost for all 50: **$0.95**.
- Checks on every vision record (no model): edges point at known boxes; a decision has ≥2 labelled
  exits; each box's words are found in an independent OCR of the crop; a model-supplied title is kept
  only if printed in the image (an invented title was caught on opioids p25).
- Status: 5 `reviewed` (the five algorithm pages, below), 39 `ocr_checked`, 6 `machine_interpreted`
  (checks failed). The 6 are labelled "not verified" in the index and the app. On the one of them
  inspected (PBM guide p6, a styled 3-step graphic) the extraction is correct and the OCR failed,
  so the check errs toward "not verified".
- Chunks carry: document id, source hash, PDF page(s), printed page label, section path, content
  types, extraction method (docling_text / tableformer / vision / pdl_row_extractor), source bboxes,
  figure ids and verification status. Figure crops are kept in `storage/figures/` and served by the app.
- Tables: header rows repeated on every chunk cut from a table; rows never split; footnotes kept at the
  table end; captions carried to a same-header continuation on the next page; tables of contents
  dropped.

### The five previously skipped flowcharts, compared box by box with the page image

| Page | Boxes | Result |
|---|---|---|
| Diabetes p21 (Module A) | 1–12 | All arrows and Yes/No labels match; box 7 rejoins before box 8; boxes 3 and 10 are terminal |
| Diabetes p22 (Module B) | 13–18 | Box 14 Yes → 15 → 16, No → 16; linear 16 → 17 → 18 |
| Opioids p25 (Module A) | 1–17 | Box 3 Yes → Module C; the No exits of 6/8/10/12/13 join the line to box 17 |
| Opioids p26 (Module B) | 18–30 | After re-cropping: 23 No → 22; 28 loops to 20; 29 No → 28, Yes → 30 |
| Opioids p27 (Module C) | 31–40 | 35 Yes and 37 Yes → 36; 40 Yes loops to 32, No loops to 39 |

The reviews were made by the AI build assistant comparing images, not by a clinician
(`docs/figure_reviews.yaml`). The bar chart (p5) and the basal-insulin figure (p8) were also compared
and match, including which bar belongs to which drug class.

## 3. Retrieval (direct hybrid search, no agent; `reports/retrieval/`)

| Set | Setup | Recall@5 | Recall@10 |
|---|---|---|---|
| Original golden (19 with PDF gold) | E | 0.675 | 0.882 |
| | F | 0.729 | 0.842 |
| Visual set (8) | E | 0.750 | 0.875 |
| | F | 0.708 | 1.000 |

F loses one gold page each on Q03, Q04 and Q13 at @10 (all ordinary text pages) and gains on V03 and
V04. Page recall does not show whether a page's content is usable: E retrieves the chart page for V06,
but its text is the chart's numbers without their series.

## 4. Agent evaluation (same scoring definitions, same harness, same day; one run each)

`evals/golden.jsonl` is unchanged; the visual/table cases are a separate file, `evals/visual.jsonl`
(8 questions: 5 flowchart branches, a chart, a 3-step diagram, a recommendation-table cell).

| Metric | Original E | Original F | Visual E | Visual F |
|---|---|---|---|---|
| Accuracy (judge; partial = 0.5) | 0.900 (16/4/0) | 0.925 (17/3/0) | 0.75 (5/2/1) | 1.00 (8/0/0) |
| Groundedness (supported claims / claims) | 0.858 | 0.887 | 0.911 | 0.703 |
| Safe (no unsupported content) | 14/20 | 16/20 | 6/8 | 5/8 |
| Citation precision / recall (all gold) | 0.790 / 0.767 | 0.791 / 0.816 | 0.489 / 0.667 | 0.740 / 0.833 |
| Gold sources returned by any tool | 48/59 | 52/59 | 13/16 | 16/16 |
| Useful (answerable, non-abstaining) | 19/19 | 19/19 | 8/8 | 8/8 |
| Latency p50 / p95 | 10.6 / 27.4 s | 10.6 / 22.2 s | 16.4 / 24.5 s | 12.7 / 26.5 s |
| Over 30 s | 1 | 0 | 0 | 1 |
| Run cost (agent + judge) | $4.27 | $4.37 | $1.62 | $1.53 |

Reading it honestly:
- Original set: F is level or slightly ahead on every metric, but these are single runs of 20
  questions; a one-question difference is within run-to-run noise. **No regression; no claimed gain.**
- Visual set: F answered all 8 correctly vs 5 correct/2 partial/1 incorrect for E (E got the chart
  question wrong). **Judged groundedness and "safe" are lower for F.** The judge's notes show two causes:
  the agent sometimes cites the appendix page while using content from the figure page, and when the
  judge reads a figure page's raw text layer (the chart's numbers without series) it treats the jumble
  as the source. One more run with `read_page` returning the page's figure interpretations (setting
  `page_figures`) scored accuracy 1.00 but groundedness 0.658 and safe 3/8, so that setting is off in
  the deployed configuration and was never run on the original set.
- 8 questions is a small set; these are directional results.

## 5. Ingestion cost (this release)

| Step | Cost | Time |
|---|---|---|
| Docling parse, 569 pages (local CPU/MPS) | $0 | 637 s once; 0 s when cached |
| Vision extraction, 50 figures | $0.95 | ~2 min (6 parallel) |
| Embeddings, 1,983 chunks (text-embedding-3-large) | $0.07 | 13 s |

## 6. Hosted serving

Live at the Lambda Function URL (deploy/aws). At this account's Lambda memory maximum (3,008 MB,
~1.7 vCPU) the cross-encoder dominated search time: 22.9 s of a 23.4 s search with 2 threads (66 s with
torch's default thread count), measured in a container limited to 1.7 CPUs. ONNX Runtime fp32 was no
faster; int8 was ~8.5 s with top-10 overlap 8/10 against the original scores. The hosted app therefore
serves `docling_norerank_structured` (same index, no cross-encoder; ~0.5 s per search):

| Set | Setup | Recall@5 | Recall@10 |
|---|---|---|---|
| Original | F (reranked) | 0.729 | 0.842 |
| Original | F0 (no reranker) | 0.744 | 0.820 |
| Visual | F (reranked) | 0.708 | 1.000 |
| Visual | F0 (no reranker) | 0.875 | 0.958 |

F0 as deployed (dense search in Pinecone `pharmacy-docs-docling-v1`, keyword search over the S3
build, no cross-encoder) was then evaluated end to end with the same harness (one run each, $5.95):

| Metric | Original F (reranked) | Original F0 (hosted) | Visual F | Visual F0 (hosted) |
|---|---|---|---|---|
| Accuracy | 0.925 (17/3/0) | 0.850 (15/4/1) | 1.00 (8/0/0) | 1.00 (8/0/0) |
| Groundedness | 0.887 | 0.878 | 0.703 | 0.667 |
| Safe | 16/20 | 15/20 | 5/8 | 4/8 |
| Useful | 19/19 | 18/19 | 8/8 | 8/8 |
| Citation precision / recall | 0.791 / 0.816 | 0.702 / 0.762 | 0.740 / 0.833 | 0.594 / 0.771 |
| Latency p50 / p95 | 10.6 / 22.2 s | 7.2 / 12.0 s | 12.7 / 26.5 s | 6.0 / 6.9 s |

Without the cross-encoder, Q19 (answered correctly with it) became "not in the documents" (graded
incorrect) and Q15 dropped to partial. **The hosted configuration is measurably less accurate on the
original set than the evaluated reranked one, and faster.** Restoring the reranker on the hosted app
needs more CPU than this account's Lambda limit (a quota increase to 10 GB / 6 vCPU) or a hosted
reranking API (a new key and a re-evaluation).

## 7. Limitations

- Mistral OCR not compared (no key).
- Rotated table text can be partly lost (diabetes p25 sub-topic).
- Six indexed figures are `machine_interpreted` (checks failed); 39 are only `ocr_checked`, not reviewed.
- The judge's groundedness on figure-based answers is lower; citation of figure pages vs. appendix
  pages needs work before claiming visual answers are better grounded.
- The visual set was written by the same assistant that built the extraction; independent questions
  would be a stronger test.
- The hosted app's setup (no cross-encoder) is retrieval-measured only.
