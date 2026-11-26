"""serve/reqtelemetry/evidence.py - the optional metadata-only JSONL evidence (G9).

One terminal record per accepted request, one per line, written by a BACKGROUND thread: the token path never touches
the disk.  The queue is bounded - when it is full the record is DROPPED and counted, never written synchronously.
"""
from __future__ import annotations

import json
import threading
import time

class EvidenceLog:
    """The optional terminal-record log: one metadata-only JSON object per accepted request, one per line.

    It is written by a BACKGROUND thread: the token path never touches the disk, and a slow disk cannot slow a
    request down.  The queue is bounded - when it is full the record is DROPPED and counted, never written
    synchronously as a fallback (that would put the disk back on the hot path).
    """

    def __init__(self, path, queue_size=1024, queue_bytes=8 << 20):
        self.path = str(path)
        self.queue_size = max(1, int(queue_size))
        # the queue is bounded by RECORDS and by BYTES: a long record cannot fill the memory (G6)
        self.queue_bytes = max(4096, int(queue_bytes))
        self.queue_size_bytes = 0
        self.lock = threading.Lock()
        self.queue = []
        self.written = 0
        self.dropped = 0
        self.errors = 0
        self.flush_incomplete = 0         # the shutdown flushes that did not finish (G6)
        self._stop = threading.Event()
        self._thread = None
        self._handle = None
        self._open()

    def _open(self):
        try:
            self._handle = open(self.path, "a", encoding="utf-8")
        except OSError:
            self._handle = None
            with self.lock:
                self.errors += 1
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="strata-telemetry-evidence")
        self._thread.start()

    def write(self, record: dict) -> bool:
        """Queue a terminal record.  True when it was queued, False when it was dropped."""
        if self._handle is None:
            return False
        try:
            line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            with self.lock:
                self.errors += 1
            return False
        with self.lock:
            if len(self.queue) >= self.queue_size or self.queue_size_bytes + len(line) > self.queue_bytes:
                self.dropped += 1              # the queue is full: the record is DROPPED and counted, never written
                return False
            self.queue.append(line)
            self.queue_size_bytes += len(line)
        return True

    def _loop(self):
        while not self._stop.is_set() or self.queue:
            with self.lock:
                pending, self.queue = self.queue, []
                self.queue_size_bytes = 0
            for line in pending:
                try:
                    self._handle.write(line + "\n")
                    self._handle.flush()
                    with self.lock:
                        self.written += 1
                except OSError:
                    with self.lock:
                        self.errors += 1
            if not pending:
                self._stop.wait(0.2)

    def flush(self, timeout=2.0):
        """Wait for the queue to be written (the shutdown path).  False when the queue was not written in time -
        the count of the incomplete shutdown flushes is published (G6)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                if not self.queue:
                    return True
            time.sleep(0.02)
        with self.lock:
            self.flush_incomplete += 1
        return False

    def close(self):
        """Stop the thread after the queue is written, and close the file."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._handle is not None:
            try:
                self._handle.close()
            except OSError:
                pass
            self._handle = None

    def counters(self) -> dict:
        with self.lock:
            # what the writer really did: the lines it wrote, the ones it dropped, the ones that failed, and the
            # queue it is holding now (G6)
            return {"written": self.written, "dropped": self.dropped, "errors": self.errors,
                    "queue_size": self.queue_size, "queue_bytes": self.queue_size_bytes,
                    "max_queue_bytes": self.queue_bytes, "path": self.path,
                    "flush_incomplete": self.flush_incomplete}
