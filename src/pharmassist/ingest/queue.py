"""The ingestion queue: Amazon SQS (or ElasticMQ through SQS_ENDPOINT_URL), a durable SQLite queue
for a laptop, or an in-process queue for tests. All three share SQS semantics: at-least-once
delivery, a visibility timeout the worker extends while a job runs, a receive count, and a
dead-letter queue.

Messages carry identifiers only ({"job_id", "version_id", "document_id"}); never secrets or text.
"""

import json
import os
import sqlite3
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from pharmassist.config import PROJECT_ROOT

MAX_SQS_VISIBILITY_S = 43200


@dataclass
class Received:
    body: dict
    receipt: str
    receive_count: int


class JobQueue(ABC):
    @abstractmethod
    def send(self, body: dict) -> str: ...

    @abstractmethod
    def receive(self, wait_s: int = 10) -> list[Received]: ...

    @abstractmethod
    def ack(self, msg: Received) -> None:
        """Delete a processed message."""

    @abstractmethod
    def retry_later(self, msg: Received, delay_s: int) -> None:
        """Make the message visible again after `delay_s` (a retry with backoff; 0 = at once)."""

    @abstractmethod
    def extend_visibility(self, msg: Received, seconds: int) -> None:
        """The heartbeat: keep the message invisible for another `seconds` while its job runs."""

    @abstractmethod
    def dead_letter(self, msg: Received, reason: str) -> None:
        """Move the message to the dead-letter queue and remove it from the main queue."""


class MemoryQueue(JobQueue):
    """In-process queue with visibility semantics, for tests and `queue.backend: memory`."""

    def __init__(self, visibility_timeout_s: int = 1800, clock=time.time):
        self.visibility, self.clock = visibility_timeout_s, clock
        self._msgs: dict[str, dict] = {}     # receipt -> {body, visible_at, receive_count}
        self.dead: list[dict] = []
        self.lock = threading.Lock()

    def send(self, body):
        mid = uuid.uuid4().hex
        with self.lock:
            self._msgs[mid] = {"body": dict(body), "visible_at": self.clock(), "receive_count": 0}
        return mid

    def receive(self, wait_s=10):
        deadline = self.clock() + wait_s
        while True:
            with self.lock:
                now = self.clock()
                ready = sorted((m["visible_at"], r) for r, m in self._msgs.items() if m["visible_at"] <= now)
                if ready:
                    receipt = ready[0][1]
                    m = self._msgs[receipt]
                    m["visible_at"] = now + self.visibility
                    m["receive_count"] += 1
                    return [Received(dict(m["body"]), receipt, m["receive_count"])]
            if self.clock() >= deadline:
                return []
            time.sleep(0.01)

    def ack(self, msg):
        with self.lock:
            self._msgs.pop(msg.receipt, None)

    def retry_later(self, msg, delay_s):
        with self.lock:
            if msg.receipt in self._msgs:
                self._msgs[msg.receipt]["visible_at"] = self.clock() + delay_s

    def extend_visibility(self, msg, seconds):
        with self.lock:
            if msg.receipt in self._msgs:
                self._msgs[msg.receipt]["visible_at"] = self.clock() + seconds

    def dead_letter(self, msg, reason):
        with self.lock:
            m = self._msgs.pop(msg.receipt, None)
            if m is not None:
                self.dead.append({"body": m["body"], "reason": reason[:500]})

    def pending(self) -> int:
        with self.lock:
            return len(self._msgs)

    def dead_letters(self) -> list[dict]:
        return list(self.dead)


class LocalQueue(JobQueue):
    """SQLite-backed queue for a laptop without ElasticMQ (`queue.backend: local`)."""

    def __init__(self, path: Path | str, visibility_timeout_s: int = 1800, max_receives: int = 3,
                 clock=time.time):
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, body TEXT, visible_at REAL, "
                        "receive_count INTEGER, dead INTEGER DEFAULT 0, reason TEXT)")
        self.visibility, self.max_receives, self.clock = visibility_timeout_s, max_receives, clock
        self.lock = threading.Lock()

    def send(self, body):
        mid = uuid.uuid4().hex
        with self.lock:
            self.db.execute("INSERT INTO messages VALUES (?,?,?,?,0,NULL)", (mid, json.dumps(body), self.clock(), 0))
        return mid

    def receive(self, wait_s=10):
        deadline = self.clock() + wait_s
        while True:
            with self.lock:
                self.db.execute("BEGIN IMMEDIATE")
                row = self.db.execute("SELECT id, body, receive_count FROM messages WHERE dead=0 AND visible_at<=? "
                                      "ORDER BY visible_at LIMIT 1", (self.clock(),)).fetchone()
                if row and row[2] >= self.max_receives:
                    # the redrive policy: too many receives without an ack
                    self.db.execute("UPDATE messages SET dead=1, reason='max receives exceeded' WHERE id=?", (row[0],))
                    self.db.execute("COMMIT")
                    continue
                if row:
                    self.db.execute("UPDATE messages SET visible_at=?, receive_count=receive_count+1 WHERE id=?",
                                    (self.clock() + self.visibility, row[0]))
                self.db.execute("COMMIT")
            if row:
                return [Received(json.loads(row[1]), row[0], row[2] + 1)]
            if self.clock() >= deadline:
                return []
            time.sleep(0.2)

    def ack(self, msg):
        with self.lock:
            self.db.execute("DELETE FROM messages WHERE id=?", (msg.receipt,))

    def retry_later(self, msg, delay_s):
        with self.lock:
            self.db.execute("UPDATE messages SET visible_at=? WHERE id=?", (self.clock() + delay_s, msg.receipt))

    def extend_visibility(self, msg, seconds):
        self.retry_later(msg, seconds)

    def dead_letter(self, msg, reason):
        with self.lock:
            self.db.execute("UPDATE messages SET dead=1, reason=? WHERE id=?", (reason[:500], msg.receipt))

    def dead_letters(self) -> list[dict]:
        return [{"body": json.loads(b), "reason": r} for b, r in
                self.db.execute("SELECT body, reason FROM messages WHERE dead=1")]

    def pending(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM messages WHERE dead=0").fetchone()[0]


class SQSQueue(JobQueue):
    """A standard SQS queue whose redrive policy points at `dlq_url`. Permanent failures are sent to
    the DLQ directly; repeated retryable failures reach it through the worker's attempt counter."""

    def __init__(self, queue_url: str, dlq_url: str, client=None, endpoint_url: str | None = None):
        if client is None:
            import boto3
            client = boto3.client("sqs", region_name=os.environ.get("AWS_REGION") or None,
                                  endpoint_url=endpoint_url or None)
        self.url, self.dlq_url, self.sqs = queue_url, dlq_url, client

    def send(self, body):
        return self.sqs.send_message(QueueUrl=self.url, MessageBody=json.dumps(body))["MessageId"]

    def receive(self, wait_s=10):
        resp = self.sqs.receive_message(QueueUrl=self.url, MaxNumberOfMessages=1, WaitTimeSeconds=min(int(wait_s), 20),
                                        MessageSystemAttributeNames=["ApproximateReceiveCount"])
        return [Received(json.loads(m["Body"]), m["ReceiptHandle"],
                         int(m.get("Attributes", {}).get("ApproximateReceiveCount", 1)))
                for m in resp.get("Messages", [])]

    def ack(self, msg):
        self.sqs.delete_message(QueueUrl=self.url, ReceiptHandle=msg.receipt)

    def retry_later(self, msg, delay_s):
        self.sqs.change_message_visibility(QueueUrl=self.url, ReceiptHandle=msg.receipt,
                                           VisibilityTimeout=min(max(int(delay_s), 0), MAX_SQS_VISIBILITY_S))

    def extend_visibility(self, msg, seconds):
        self.retry_later(msg, seconds)

    def dead_letter(self, msg, reason):
        self.sqs.send_message(QueueUrl=self.dlq_url,
                              MessageBody=json.dumps({**msg.body, "dead_letter_reason": reason[:500]}))
        self.ack(msg)


class QueueConfigError(RuntimeError):
    """A required queue setting or environment variable is missing."""


def queue_from_config(cfg: dict) -> JobQueue:
    """The queue the `queue:` block of config.yaml names: sqs (URLs and the optional ElasticMQ
    endpoint from the environment), local (SQLite) or memory."""
    q = cfg["queue"]
    backend = q.get("backend", "sqs")
    if backend == "sqs":
        url, dlq = os.environ.get(q["queue_url_env"]), os.environ.get(q["dlq_url_env"])
        if not url or not dlq:
            raise QueueConfigError(f"set {q['queue_url_env']} and {q['dlq_url_env']} for queue.backend: sqs")
        return SQSQueue(url, dlq, endpoint_url=os.environ.get(q.get("endpoint_env", "SQS_ENDPOINT_URL")))
    if backend == "local":
        p = PROJECT_ROOT / q.get("local_db", "storage/queue.sqlite")
        p.parent.mkdir(parents=True, exist_ok=True)
        return LocalQueue(p, q.get("visibility_timeout_s", 1800), q.get("max_attempts", 3))
    if backend == "memory":
        return MemoryQueue(q.get("visibility_timeout_s", 1800))
    raise QueueConfigError(f"unknown queue.backend {backend!r}")


open_queue = queue_from_config   # the name the API (app/main.py) imports
