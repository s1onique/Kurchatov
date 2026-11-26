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

    ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-02 (A5): the writer's counters are exact:

      * accepted_records  - the records the writer took responsibility for;
      * written_records   - the records the worker actually wrote;
      * failed_records    - the records the worker could not write (a write error, or a handle that was gone);
      * dropped_records   - the records the writer refused (the queue was full);
      * outstanding_records / outstanding_bytes - what the writer still holds (queued AND being written);
      * incomplete_flushes - the flushes that did not finish in time.

    The BYTES are the serialized UTF-8 bytes of the line, framing included - a character count is not a byte
    count, and a record with multi-byte characters would slip past a byte budget that counted characters.
    A successful flush means every record accepted before it reached a terminal writer outcome; a flush that times
    out says so instead of pretending the evidence is on the disk.
    """

    def __init__(self, path, queue_size=1024, queue_bytes=8 << 20):
        self.path = str(path)
        self.queue_size = max(1, int(queue_size))
        # the queue is bounded by RECORDS and by BYTES: a long record cannot fill the memory (G6)
        self.queue_bytes = max(4096, int(queue_bytes))
        self.queue_size_bytes = 0
        self.lock = threading.Lock()
        self.queue = []
        self.writing = 0                  # the records the worker took out of the queue and is writing now
        # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-03 (G3): the counter domains are exact and apart:
        #
        #     submitted = accepted + refused
        #     accepted  = written + failed + outstanding
        #
        # A submission that is REFUSED is not an accepted record: it is counted in its own domain (the
        # serialization, the capacity or the shutdown), never in the accepted one.  The outstanding records are
        # what the writer still holds: the QUEUED ones AND the ones it has DETACHED and is writing.
        self.submitted = 0
        self.accepted = 0
        self.written = 0
        self.failed = 0                  # accepted records that failed while they were written
        self.refused = 0
        self.init_failures = 0           # the log could not be opened at all
        self.serialization_refusals = 0  # the record could not be serialized
        self.capacity_refusals = 0       # the queue was full
        self.shutdown_refusals = 0       # the acceptance boundary was closed
        self.dropped = 0                 # the older name of the refusals
        self.errors = 0                  # the same as `failed`: kept for the older name
        self.outstanding_records = 0
        self.outstanding_bytes = 0
        self.flush_incomplete = 0         # the shutdown flushes that did not finish (G6)
        self.closed = False              # the acceptance boundary (G3)
        self._handle_closed = False
        self._stop = threading.Event()
        self._thread = None
        self._handle = None
        self._open()

    def _open(self):
        try:
            # BINARY: the writer accounts the UTF-8 bytes of the line, and it writes exactly those bytes
            self._handle = open(self.path, "ab")
        except OSError:
            self._handle = None
            with self.lock:
                # AMENDMENT-03 (G3): an initialization failure is NEITHER an accepted record nor a failed
                # accepted record: it has its own domain.
                self.init_failures += 1
                self.errors += 1
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="strata-telemetry-evidence")
        self._thread.start()

    def write(self, record: dict) -> bool:
        """Queue a terminal record.  True when it was queued, False when it was refused.

        ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-03 (G3): the bound is checked against the
        AUTHORITATIVE outstanding counter - what the writer really holds, the queued records AND the ones it has
        detached and is writing.  The old check (`len(queue) + writing`) left the detached records out, so the
        writer could hold more records than its own limit said.
        """
        with self.lock:
            self.submitted += 1
            if self._handle is None:
                # no handle: the record is REFUSED, and it is counted as such (AMENDMENT-02, A5)
                if self.closed:
                    self.shutdown_refusals += 1
                else:
                    self.init_failures += 1
                self.refused += 1
                self.dropped += 1
                self.errors += 1
                return False
            if self.closed:
                # the acceptance boundary is closed: a submission that races the shutdown is refused, never
                # accepted and then abandoned
                self.shutdown_refusals += 1
                self.refused += 1
                self.dropped += 1
                return False
        try:
            line = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        except (TypeError, ValueError):
            with self.lock:
                self.serialization_refusals += 1
                self.refused += 1
                self.dropped += 1
                self.errors += 1
            return False
        with self.lock:
            # the bound counts what the writer HOLDS: the queued records AND the one being written right now
            if self.outstanding_records >= self.queue_size \
                    or self.outstanding_bytes + len(line) > self.queue_bytes:
                self.capacity_refusals += 1      # the queue is full: the record is REFUSED and counted
                self.refused += 1
                self.dropped += 1
                return False
            self.queue.append(line)
            self.queue_size_bytes += len(line)
            self.outstanding_records += 1
            self.outstanding_bytes += len(line)
            self.accepted += 1
        return True

    def _loop(self):
        while True:
            with self.lock:
                pending, self.queue = self.queue, []
                self.queue_size_bytes = 0
            if not pending:
                with self.lock:
                    if self.queue:
                        continue               # something arrived while we looked: take it
                    if self._stop.is_set():
                        # the acceptance boundary is closed (the stop is set together with it), so no record can
                        # arrive any more: nothing is left behind
                        return
                self._stop.wait(0.05)
                continue
            for line in pending:
                with self.lock:
                    self.writing += 1
                try:
                    self._handle.write(line)
                    self._handle.flush()
                    with self.lock:
                        self.written += 1
                except OSError:
                    with self.lock:
                        self.failed += 1
                        self.errors += 1
                finally:
                    with self.lock:
                        self.writing -= 1
                        self.outstanding_records -= 1
                        self.outstanding_bytes -= len(line)

    def flush(self, timeout=2.0):
        """Wait for the writer to be done with every record it accepted (the shutdown path).

        False when the records were not written in time - the count of the incomplete shutdown flushes is published
        (G6) and the evidence is NOT reported as durable.  The clock is MONOTONIC.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                if self.outstanding_records == 0:
                    return True
            time.sleep(0.01)
        with self.lock:
            self.flush_incomplete += 1
        return False

    def close(self):
        """Stop the thread after the queue is written, and close the file.

        The worker owns the file handle until it has stopped using it: the handle is closed only after the thread
        has ended, so a worker that is still writing never writes to a closed handle.

        ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-03 (G3): the acceptance boundary closes ATOMICALLY, in
        the same lock the submissions take, BEFORE the worker is told to stop: a submission that races the
        shutdown is either accepted before the boundary (and then the worker writes it) or refused (and then it
        is counted as a shutdown refusal).  Nothing is accepted and abandoned.  When the worker does not stop in
        time, the handle is closed LATER - by a reaper that waits for the worker - never while it is in use.
        """
        with self.lock:
            self.closed = True                 # the acceptance boundary
            self._stop.set()                   # and the worker's signal, in the same breath
        stopped = True
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            stopped = not self._thread.is_alive()
        if not stopped:
            with self.lock:
                self.flush_incomplete += 1       # the writer did not stop: the evidence is incomplete
            self._start_reaper()
            return
        self._close_handle()

    def _start_reaper(self):
        """Close the handle when the worker has really stopped (G3).  The handle is never closed while the
        worker may still be using it."""
        worker = self._thread

        def reap():
            if worker is not None:
                worker.join()
            self._close_handle()

        threading.Thread(target=reap, daemon=True, name="strata-telemetry-evidence-reaper").start()

    def _close_handle(self):
        """Close the file handle once, and only when no worker can be using it."""
        with self.lock:
            if self._handle_closed:
                return
            self._handle_closed = True
            handle, self._handle = self._handle, None
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass

    def counters(self) -> dict:
        with self.lock:
            # what the writer really did: the lines it wrote, the ones it refused, the ones that failed, and the
            # queue it is holding now (G6)
            return {"written": self.written, "dropped": self.dropped, "errors": self.errors,
                    "queue_size": self.queue_size, "queue_bytes": self.queue_size_bytes,
                    "max_queue_bytes": self.queue_bytes, "path": self.path,
                    "flush_incomplete": self.flush_incomplete,
                    # AMENDMENT-02 (A5): the exact domains
                    "accepted_records": self.accepted, "written_records": self.written,
                    "failed_records": self.failed, "dropped_records": self.dropped,
                    "outstanding_records": self.outstanding_records,
                    "outstanding_bytes": self.outstanding_bytes,
                    "incomplete_flushes": self.flush_incomplete,
                    # AMENDMENT-03 (G3): the exact domains of the acceptance boundary.  The identity
                    #     submitted = accepted + refused
                    #     accepted  = written + failed + outstanding
                    # holds at every moment, and the refusals are told apart by their own cause.
                    "submitted_records": self.submitted, "refused_records": self.refused,
                    "initialization_failures": self.init_failures,
                    "serialization_refusals": self.serialization_refusals,
                    "capacity_refusals": self.capacity_refusals,
                    "shutdown_refusals": self.shutdown_refusals,
                    "write_failures": self.failed,
                    "closed": self.closed}
