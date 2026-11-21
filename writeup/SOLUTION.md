# PharmAssist: the solution (run it, how it works, operations)

> Code paths in this document are relative to the [repository root](../); the write-ups live in `writeup/`.

**In 20 seconds.** PharmAssist is a web app for pharmacy staff: one operational question in, one cited answer
out in about 15 seconds of reading, grounded only in 11 public VA, Medicare Part D and NY Medicaid documents.
Staff ask and rate; admins see every conversation, upload, re-index or remove documents, and watch spend. It
was deployed on AWS at pharmassist.aishwaryabhanage.com (`evidence/live_check_2026-10-18.log`, `evidence/screenshots/`)
and runs locally with one Docker command from public images. Design: [DESIGN.md](DESIGN.md); measured results:
[EVALUATION.md](EVALUATION.md); eight answers verbatim: [EXAMPLES.md](EXAMPLES.md).

## Run it in 2 minutes

```bash
git clone https://github.com/AishwaryaBhanage/PharmaAssist.git && cd PharmaAssist
cp .env.example .env          # put your OPENAI_API_KEY in it (ANTHROPIC_API_KEY too for the fallback model)
docker compose -f deploy/docker-compose.yml -f deploy/prebuilt.override.yml --env-file .env up
```

This pulls two public images, `abhanage/pharmassist-v2-web` and `abhanage/pharmassist-v2-ingest` on Docker Hub
(Intel and Apple Silicon; `deploy/prebuilt.override.yml`), and starts Postgres 16 + pgvector, Valkey, a local
SQS and S3, the API and the ingestion worker. The seed step loads the 11 documents from the checked-in build
(1,983 chunks with vectors, 3,520 table rows, 50 figure records; `scripts/seed_local.py`) and creates demo
accounts; no model spend. No Node or Python needed. To build from this checkout instead:
`docker compose up --build` (`compose.yaml`; a few minutes the first time).

Open **http://localhost:8000** and sign in:

| Account | Password | Sees |
|---|---|---|
| `admin@pharmassist.local` | `admin-password-1` | Ask + Admin (conversations, ratings, documents, jobs, users, cache, spend) |
| `staff1@pharmassist.local` | `staff-password-1` | Ask + own conversations |

Try, in order: "Is Trulicity preferred under NY Medicaid?" (a cited answer; 5.1 s in production,
`evidence/screenshots/ask-answer.png`); the same question again (from the cache, 0.4 s in production,
`evidence/live_check_2026-10-18.log`); "What is the capital of France?" (exactly `No answer found in knowledge
base`, `evidence/screenshots/ask-no-answer.png`); then, as admin, upload a one-page PDF under Documents and watch
the job go queued → active and the content become answerable. Fresh answers use your API key, about $0.11 each
(`reports/evals/v2_2026-10-18_0903/summary.md`); repeats are free. `docker compose down -v` removes the data.

## How it works (one page)

```
Browser (React) ── /api/v1 ──▶ FastAPI (auth, /ask, conversations, feedback, admin)
                                 │  question embedding ─▶ Valkey semantic cache (cosine ≥ 0.90 ⇒ stored answer + citations)
                                 │  agent: OpenAI gpt-5.5 ─▶ Claude Sonnet on failure; tools: hybrid search, read_page, drug lookups
                                 ├─ PostgreSQL + pgvector: chunks, embeddings, full-text, documents, users, conversations, feedback, jobs
                                 └─ S3: source files, figure crops, uploads
admin upload ─▶ S3 + job row ─▶ SQS ─▶ worker (Docling, vision, chunking, embeddings) ─▶ Postgres ─▶ version activated
```

**Answering.** Each question stands alone (`REQUIREMENTS.md`: not a chat); the UI only groups them into
conversations. The question is embedded once; if a stored question is within cosine 0.90 the stored answer and
citations return in under a second with a "cached" badge naming the matched question (`src/pharmassist/cache/valkey.py`).
Otherwise an agent with at most 6 lookups and a 25 s deadline searches PostgreSQL (pgvector dense search plus
full-text, fused with RRF, reciprocal rank fusion), reads pages, and looks drugs up in the VA formulary and NY
PDL rows (`src/pharmassist/agent/`). It answers only from returned text, states the program assumption, names
the precedence rule it applied, and declines non-pharmacy questions (`out_of_scope`, `docs/PROMPTS.md`).

**The no-answer rule.** An answer is returned only when the model answered **and** at least one citation points
at a page or row a tool returned in this request; anything else is exactly `No answer found in knowledge base`
and is never cached (`app/answer_service.py`, `src/pharmassist/agent/loop.py`). Measured: 0 answers without
citations, 0 citations failing the check, Q20 declined correctly (`v2_2026-10-18_0903/summary.md`).

**Retrieval.** Small chunks (350 tokens, with heading path) are matched; the enclosing section (≤ 1,500 tokens)
is read. Formulary and PDL rows are exact lookups; flowcharts printed as images were interpreted once by a
vision model and checked against OCR (`reports/parsing/VISUAL_EXTRACTION.md`). Why: [DESIGN.md](DESIGN.md) "Architecture".

**Ingestion.** `POST /api/v1/admin/documents` validates the file (PDF or XLSX by content, 50 MB, 400 pages,
`config.yaml` `uploads`), stores it in S3, records a version and a job, and queues it. The worker parses with
Docling, interprets figures, chunks, embeds, verifies counts and activates the version in one transaction; the
old version is superseded and the cache generation moves on (`src/pharmassist/ingest/`). Failures retry three
times, then land in a dead-letter queue with the error shown in the admin UI. Admins can also re-index a
document or remove it from the index while keeping its file (`DELETE /api/v1/admin/documents/{id}/index`,
`app/admin.py`). Scanned, image-only PDFs are chunked from their OCR text.
Measured on production, 2026-10-18: upload to active in 15 s with a cold worker (`evidence/live_check_2026-10-18.log`)
and 5 s with the warm worker; remove-from-index returned 200 with counts, the document's question then
returned the no-answer sentence, re-indexing took 5 s and it was answerable again (production run, admin API).

**Citations.** Each citation is a document title plus page, opening the stored PDF at that page
(`evidence/screenshots/citation-source.png`); a page with an interpreted figure links the crop
(`frontend/src/components/ask/CitationList.tsx`, `FigureNote.tsx`).

## Operations

**Configuration.** `config.yaml` holds what experiments change: `llm` (primary and fallback models, prices,
retries, embeddings), `search`, `cache` (threshold 0.90, TTL), `auth`, `uploads`, `limits_v2` (10/min and
100/day per user, 500/day global, $10/day spend) and `tracing_v2`. `.env` holds keys and URLs; never commit it.

**Authentication and roles.** Signup creates a `staff` account; admins promote or deactivate users. Access
tokens are 15-minute JWTs; the refresh token is a rotating HttpOnly cookie, revoked on logout and on any role
change (`app/auth.py`, `config.yaml` `auth`). Set `APP_INSECURE_COOKIES=1` on plain http.

**Tracing.** With `LANGSMITH_TRACING=true` each answer is one LangSmith run (project `pharmassist`)
with question, answer, citations, provider, model, fallback, cached flag, latency, cost and tokens, and child
runs per model call, tool call and retrieval. `LANGSMITH_CONTENT_MODE=metadata` keeps content out.

**Hosting on AWS (us-east-1).** NLB with two Elastic IPs → WAF → ALB (HTTPS) → two `t4g.large` app servers,
RDS PostgreSQL, ElastiCache Valkey, SQS and a Fargate ingestion worker with one task kept warm
(`WorkerMinCount`, `deploy/aws/v2/template.yaml`). One CloudFormation stack; bootstrap, certificate, DNS, deploy
and teardown are in [`deploy/aws/v2/README.md`](../deploy/aws/v2/README.md). Cost: ≈ $197/month always on plus
≈ $144/month for the warm worker (same README, "Cost"), plus model spend bounded by the daily cap.
Console views (account access required): the
[CloudFormation stack](https://us-east-1.console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks?filteringText=pharmassist),
[API logs](https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#logsV2:log-groups/log-group/$252Fec2$252Fpharmassist-api),
[worker logs](https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#logsV2:log-groups/log-group/$252Fecs$252Fpharmassist-v2-ingest),
[ECS cluster](https://us-east-1.console.aws.amazon.com/ecs/v2/clusters/pharmassist-v2/services?region=us-east-1),
[RDS](https://us-east-1.console.aws.amazon.com/rds/home?region=us-east-1#database:id=pharmassist-v2;is-cluster=false),
[SQS](https://us-east-1.console.aws.amazon.com/sqs/v3/home?region=us-east-1#/queues),
[WAF](https://us-east-1.console.aws.amazon.com/wafv2/homev2/web-acls?region=us-east-1), and
[LangSmith](https://smith.langchain.com).

**From source** (from the repository root, Python 3.12 in the repo's `.venv`):

| Step | Command |
|---|---|
| Services | `docker compose up -d postgres valkey elasticmq s3 createbuckets` |
| Install | `uv pip install --python .venv/bin/python -e ".[all]"` (one dependency list in `pyproject.toml`; on a machine without a GPU install `torch==2.14.1` from the CPU index first) |
| Env | `cp .env.example .env`; set `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `JWT_SECRET` |
| Schema + data | `PYTHONPATH=src .venv/bin/python scripts/seed_local.py` (≈ 30 s, no API spend) |
| Frontend | `cd frontend && npm ci && npm run build` (the API serves `frontend/dist`) |
| API | `.venv/bin/uvicorn app.main:app --port 8000` (`/health/ready` checks Postgres, cache, storage) |
| Worker | `.venv/bin/python scripts/ingest_worker.py` (`--once` drains the queue and exits) |
| Tests | `.venv/bin/python -m pytest -q` (657 collected, 57 of them integration; `cd frontend && npm test` for the 28 frontend tests) |
| Evaluation | `.venv/bin/python scripts/run_eval.py --label my_change --deepeval` (paid; method and all runs in [EVALUATION.md](EVALUATION.md) §6) |
