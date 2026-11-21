# CLAUDE.md

## Environment
- Python 3.12 in `.venv` at the repo root, created with uv. Install packages with `uv pip`, never plain `pip`.
- Run everything with `.venv/bin/python`. `pharmassist` is installed editable, so no `PYTHONPATH` is needed.

## Requirements
- Product requirements are in `REQUIREMENTS.md`. Read it before designing or changing answer behavior.

## Key decisions
- v2 (design in `writeup/DESIGN.md`, evaluation in `writeup/EVALUATION.md`; the write-ups live in `writeup/`):
  PostgreSQL + pgvector is the store for documents, chunks, embeddings, users, conversations and feedback.
  The `documents` table is the source of truth for the corpus; `docs/catalog.yaml` only seeds it
  (`scripts/migrate_v1_to_pg.py`). Pinecone, DynamoDB and the Lambda app are gone.
- LLM routing: OpenAI `gpt-5.5` first, `claude-sonnet-5-5` on failure (`llm:` in `config.yaml`); one canonical
  message format in `src/pharmassist/llm/`. Any non-answered or uncited result returns exactly
  "No answer found in knowledge base".
- Semantic cache in Valkey (cosine ≥ 0.90 returns the stored answer with its citations); JWT auth with staff/admin roles;
  uploads go through SQS to the ingestion worker (`src/pharmassist/ingest/`).
- `config.yaml` holds the settings experiments change; API keys and URLs go in `.env`.
- Search uses hybrid mode (keyword + dense, fused with RRF) by default; `pharmassist.search.hybrid` over PostgreSQL
  serves the app.
- Local services for development: `deploy/docker-compose.yml` (Postgres+pgvector, Valkey, ElasticMQ, S3).

## Working rules
- Always plan before writing code.
- Never commit without the user's review.
- Never add Co-Authored-By lines to commit messages.
