"""The agent behind /ask, behind one class so the API never imports the LLM or agent packages at
import time: `AnswerService.embed()` embeds a question once (reused by the cache and dense search)
and `answer()` runs `pharmassist.agent.loop.ask` on a bounded worker pool with the server-side
ceiling `app.timeout_s`. Tests inject `ask_fn` and `embed_fn`; production builds the router
(`pharmassist.llm.router.router_from_config`) and the tools (`pharmassist.agent.tools.ToolBox`)
lazily on first use. No trace file is written (save_trace=False); LangSmith telemetry is the loop's.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Callable

from pharmassist.config import PROJECT_ROOT

log = logging.getLogger("pharmassist.app")


class AnswerTimeout(Exception):
    pass


class AnswerService:
    def __init__(self, cfg: dict, *, ask_fn: Callable | None = None, embed_fn: Callable | None = None,
                 store=None, storage=None, router=None, tools=None):
        self.cfg = cfg
        app_cfg = cfg.get("app") or {}
        self.timeout_s = float(app_cfg.get("timeout_s", 35))
        self.ask_fn, self.embed_fn = ask_fn, embed_fn
        self.store, self.storage = store, storage
        self._router, self._tools = router, tools
        self._lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=int(app_cfg.get("max_concurrent", 4)), thread_name_prefix="ask")

    # ---- lazy wiring to streams A and B ----
    def router(self):
        if self._router is None:
            with self._lock:
                if self._router is None:
                    from pharmassist.llm.router import router_from_config
                    self._router = router_from_config(self.cfg)
        return self._router

    def tools(self, question: str | None = None):
        """A fresh ToolBox per question: it accumulates the pages seen and the evidence returned, and
        it searches the original question alongside the agent's queries. An injected one (tests) is shared."""
        if self._tools is not None:
            return self._tools
        from pharmassist.agent.tools import ToolBox
        from pharmassist.search.hybrid import search as search_fn
        return ToolBox(self.store, search_fn, self.embed, self.cfg, pdf_path=self.pdf_path, question=question)

    def pdf_path(self, doc_id: str) -> Path | None:
        """The local file read_page opens: the active version fetched from object storage into
        `storage.pdf_cache_dir` on first use, or the bundled copy under docs/ in development."""
        from pharmassist.catalog import docs_dir
        entry = (self.store.documents.catalog() if self.store else {}).get(doc_id) or {}
        local = docs_dir() / entry["file"] if entry.get("file") else None
        if local and local.exists():
            return local
        doc = self.store.documents.get_document(doc_id) if self.store else None
        version = self.store.documents.get_version(doc.active_version_id) if doc and doc.active_version_id else None
        if version is None or self.storage is None:
            return None
        cache_dir = PROJECT_ROOT / ((self.cfg.get("storage") or {}).get("pdf_cache_dir") or "storage/pdf_cache")
        target = cache_dir / doc_id / f"{version.id}.pdf"
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.storage.get_bytes(version.s3_key))
        return target

    def configured(self) -> bool:
        """Readiness: an injected ask function, or the primary/fallback provider keys present."""
        import os
        if self.ask_fn is not None:
            return True
        return bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))

    # ---- the two operations /ask uses ----
    def embed(self, text: str) -> list[float]:
        if self.embed_fn is not None:
            return list(self.embed_fn(text))
        return list(self.router().embed([text])[0])

    def _ask(self, question: str, request_id: str, context: dict) -> dict:
        if self.ask_fn is not None:
            return self.ask_fn(question, request_id=request_id, context=context, cfg=self.cfg, save_trace=False)
        from pharmassist.agent import loop
        return loop.ask(question, router=self.router(), tools=self.tools(question), cfg=self.cfg, context=context,
                        request_id=request_id, save_trace=False)

    def answer(self, question: str, *, request_id: str, context: dict | None = None) -> dict:
        future = self.pool.submit(self._ask, question, request_id, context or {})
        try:
            return future.result(timeout=self.timeout_s)
        except FutureTimeout as e:
            raise AnswerTimeout() from e
