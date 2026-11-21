"""The v2 ingestion pipeline: admin uploads become queued jobs; a separate worker parses (Docling),
extracts figures, chunks, embeds and writes one document version into the store, verifies it and
activates it. Nothing here logs secrets or document text; logs carry ids and counts only."""
