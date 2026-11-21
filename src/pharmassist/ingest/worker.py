"""The ingestion consumer: one queue message = one job = one document version to build.

    receive -> claim (job running, attempt+1) -> build_version in a thread, heartbeat from the main
    thread (visibility extended, job heartbeat_at touched) -> ack + job succeeded

- Duplicate deliveries of a finished job are acknowledged and skipped.
- Stale: a job whose document has a newer version with a live job is skipped (job `skipped`, the
  version `superseded`), so an older upload never overwrites a newer one.
- TransientError (provider, storage, store failures and anything unexpected): the message comes back
  after an exponential backoff until `queue.max_attempts` receives, then it goes to the dead-letter
  queue, the job is `dead_letter` and the version `failed`.
- PermanentError: dead-letter at once, job `failed`, version `failed` with the readable message.
- A failed build's rows are deleted; a version is visible to readers only once `activate` ran.
- SIGTERM: no new messages are taken; the running job gets `queue.shutdown_grace_s` to finish, then
  its message is released (visible again) and the process exits.

Logs carry ids, stages, attempts and counts; never document text or secrets.
"""

import logging
import os
import signal
import socket
import tempfile
import threading
import time
from pathlib import Path

from pharmassist.embedders.base import TransientError
from pharmassist.ingest.pipeline import PermanentError, build_version
from pharmassist.ingest.queue import JobQueue, Received
from pharmassist.store.protocols import Conflict

log = logging.getLogger("pharmassist.ingest.worker")

FINISHED = ("succeeded", "failed", "dead_letter", "skipped")
LIVE_JOB = ("queued", "running", "succeeded")


class Interrupted(Exception):
    """Shutdown arrived and the grace period passed before the build finished."""


def default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


class Worker:
    def __init__(self, store, queue: JobQueue, *, embed_fn, cfg: dict, build=build_version, worker_id: str | None = None,
                 storage=None, tools=None, sleep=time.sleep, clock=time.monotonic, work_root: Path | None = None):
        q = cfg["queue"]
        self.store, self.queue, self.embed_fn, self.cfg = store, queue, embed_fn, cfg
        self.build, self.storage, self.tools = build, storage, tools
        self.worker_id = worker_id or default_worker_id()
        self.max_attempts = int(q.get("max_attempts", 3))
        self.backoff_s = float(q.get("retry_backoff_s", 30))
        self.heartbeat_s = float(q.get("heartbeat_s", 300))
        self.visibility_s = int(q.get("visibility_timeout_s", 1800))
        self.grace_s = float(q.get("shutdown_grace_s", 110))   # under Fargate's 120 s stopTimeout
        self.sleep, self.clock, self.work_root = sleep, clock, work_root
        self.stop_requested, self.stop_at = False, None
        self.heartbeats = 0

    # ---- lifecycle ----
    def request_stop(self, *_) -> None:
        """SIGTERM/SIGINT: finish the current job (bounded) and return from run()."""
        if not self.stop_requested:
            self.stop_requested, self.stop_at = True, self.clock()
            log.info("worker=%s stop requested", self.worker_id)

    def install_signal_handlers(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self.request_stop)

    def run(self, once: bool = False, max_jobs: int | None = None, wait_s: int = 20) -> int:
        """Consume until stopped; `once` does a single receive. Returns the number of jobs handled."""
        n = 0
        while not self.stop_requested:
            for msg in self.queue.receive(wait_s=wait_s):
                self.handle(msg)
                n += 1
            if once or (max_jobs and n >= max_jobs):
                break
        return n

    # ---- one message ----
    def handle(self, msg: Received) -> str:
        body = msg.body if isinstance(msg.body, dict) else {}
        job_id, version_id = body.get("job_id"), body.get("version_id")
        job = self.store.documents.get_job(job_id) if job_id else None
        if job is None:
            log.warning("job=%s unknown; message acknowledged", job_id)
            self.queue.ack(msg)
            return "unknown"
        if job.status in FINISHED:
            log.info("job=%s already %s; duplicate delivery acknowledged", job.id, job.status)
            self.queue.ack(msg)
            return "duplicate"
        version = self.store.documents.get_version(job.version_id or version_id)
        if version is None:
            self.store.documents.update_job(job.id, status="failed", error="version row missing", finished=True)
            self.queue.dead_letter(msg, "version row missing")
            return "failed"
        newer = self._newer_version(version)
        if newer:
            reason = f"stale: version {newer} of {version.document_id} was uploaded later"
            self.store.documents.update_job(job.id, status="skipped", error=reason, finished=True)
            if version.status != "active":
                self.store.documents.set_version_status(version.id, "superseded", error=reason)
            self.queue.ack(msg)
            log.info("job=%s version=%s document=%s outcome=skipped (%s)", job.id, version.id, version.document_id, reason)
            return "skipped"

        attempt = job.attempt + 1
        self.store.documents.update_job(job.id, status="running", attempt=attempt, worker_id=self.worker_id,
                                        stage="claimed", error=None, started=True, heartbeat=True)
        log.info("job=%s version=%s document=%s attempt=%d/%d claimed", job.id, version.id, version.document_id,
                 attempt, self.max_attempts)
        t0 = self.clock()
        try:
            stats = self._build_with_heartbeat(msg, job, version)
            self.queue.ack(msg)
            self.store.documents.update_job(job.id, status="succeeded", stage="active", finished=True)
            outcome = "succeeded"
            log.info("job=%s version=%s outcome=succeeded chunks=%s figures=%s table_rows=%s seconds=%.0f", job.id,
                     version.id, stats.get("chunks"), stats.get("figures"), stats.get("table_rows"), self.clock() - t0)
        except Interrupted:
            self._release(msg, job, version, "interrupted by worker shutdown; will be retried")
            outcome = "interrupted"
        except PermanentError as e:
            self._fail(msg, job, version, f"{e}", status="failed")
            outcome = "failed"
        except Conflict as e:   # activation refused: the version changed state under us
            self._fail(msg, job, version, f"activation refused: {e}", status="failed")
            outcome = "failed"
        except TransientError as e:
            outcome = self._retry_or_dead_letter(msg, job, version, attempt, f"transient: {e}")
        except Exception as e:   # store or unexpected failures: retry, bounded by max_attempts
            outcome = self._retry_or_dead_letter(msg, job, version, attempt, f"{type(e).__name__}: {str(e)[:200]}")
        return outcome

    def _newer_version(self, version) -> str | None:
        """Id of a version of the same document created after this one whose latest job is live."""
        if version.created_at is None:
            return None
        for v in self.store.documents.list_versions(version.document_id):
            if v.id == version.id or v.status in ("failed", "superseded") or v.created_at is None:
                continue
            if v.created_at <= version.created_at:
                continue
            page = self.store.documents.list_jobs(version_id=v.id, limit=1)
            if page.items and page.items[0].status in LIVE_JOB:
                return v.id
        return None

    def _build_with_heartbeat(self, msg: Received, job, version) -> dict:
        """The build runs in a daemon thread; this thread extends the message's visibility and the
        job's heartbeat every `heartbeat_s`, and enforces the shutdown grace period."""
        result: dict = {}

        def progress(stage: str):
            self.store.documents.update_job(job.id, stage=stage, heartbeat=True)

        def target():
            try:
                with tempfile.TemporaryDirectory(prefix=f"ingest-{version.id}-", dir=self.work_root) as tmp:
                    result["stats"] = self.build(
                        self.store, version, work_dir=Path(tmp), embed_fn=self.embed_fn, cfg=self.cfg,
                        log=lambda m: log.info("job=%s version=%s %s", job.id, version.id, m),
                        progress=progress, storage=self.storage, tools=self.tools)
            except BaseException as e:   # handed to the main thread, classified there
                result["error"] = e

        t = threading.Thread(target=target, name=f"build-{version.id}", daemon=True)
        t.start()
        last_beat = self.clock()
        tick = max(0.01, min(1.0, self.heartbeat_s / 2))
        while t.is_alive():
            t.join(timeout=tick)
            now = self.clock()
            if now - last_beat >= self.heartbeat_s and t.is_alive():
                self.queue.extend_visibility(msg, self.visibility_s)
                self.store.documents.update_job(job.id, heartbeat=True)
                self.heartbeats += 1
                last_beat = now
            if self.stop_requested and now - self.stop_at > self.grace_s and t.is_alive():
                raise Interrupted()
        if "error" in result:
            raise result["error"]
        return result["stats"]

    # ---- outcomes ----
    def _delete_content(self, version) -> None:
        try:
            self.store.content.delete_version_content(version.id)
        except Exception as e:
            log.warning("version=%s content cleanup failed: %s", version.id, type(e).__name__)

    def _fail(self, msg: Received, job, version, reason: str, status: str) -> None:
        reason = reason[:500]
        self._delete_content(version)
        self.store.documents.set_version_status(version.id, "failed", error=reason)
        self.store.documents.update_job(job.id, status=status, error=reason, finished=True)
        self.queue.dead_letter(msg, reason)
        log.warning("job=%s version=%s outcome=%s error=%s", job.id, version.id, status, reason)

    def _retry_or_dead_letter(self, msg: Received, job, version, attempt: int, reason: str) -> str:
        if attempt >= self.max_attempts:
            self._fail(msg, job, version, f"{reason} (after {attempt} attempts)", status="dead_letter")
            return "dead_letter"
        delay = int(self.backoff_s * 2 ** (attempt - 1))
        self.store.documents.set_version_status(version.id, "queued", error=reason[:500])
        self.store.documents.update_job(job.id, status="queued", error=reason[:500])
        self.queue.retry_later(msg, delay)
        log.warning("job=%s version=%s outcome=retry attempt=%d delay_s=%d error=%s", job.id, version.id, attempt,
                    delay, reason[:200])
        return "retry"

    def _release(self, msg: Received, job, version, reason: str) -> None:
        self.store.documents.set_version_status(version.id, "queued", error=reason)
        self.store.documents.update_job(job.id, status="queued", error=reason)
        self.queue.retry_later(msg, 0)
        log.warning("job=%s version=%s outcome=interrupted", job.id, version.id)


def run_forever(store, queue: JobQueue, *, embed_fn, cfg: dict, once: bool = False, max_jobs: int | None = None,
                worker_id: str | None = None, storage=None, tools=None, signals: bool = True, **kw) -> int:
    """Build a Worker and consume the queue (the script's entrypoint; tests pass `signals=False`)."""
    w = Worker(store, queue, embed_fn=embed_fn, cfg=cfg, worker_id=worker_id, storage=storage, tools=tools, **kw)
    if signals:
        w.install_signal_handlers()
    log.info("worker=%s started once=%s max_jobs=%s", w.worker_id, once, max_jobs)
    n = w.run(once=once, max_jobs=max_jobs)
    log.info("worker=%s stopped after %d jobs", w.worker_id, n)
    return n
