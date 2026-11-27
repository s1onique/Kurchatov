"""serve/test_telemetry_amendment01_final.py - the witnesses of
ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (F1-F5).

Every witness here uses the PRODUCTION path: the dispatch boundary creates the invocation receipt and names its
prompt domain, the engine's terminal evidence arrives through apply_engine, and the request is closed through
ServerTelemetry.finish.  The witnesses assert the AGGREGATE counters and the POPULATION identities - never only
the helper that classifies a domain.

The non-vacuity (the reversal of each correction) is in
tools/test_telemetry_amendment01_final_mutations.py.
"""
from __future__ import annotations

import threading
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from serve.reqtelemetry import RequestRecord, ServerTelemetry, TelemetryStore, apply_engine, new_invocation_id


def _dispatched(record, ordinal=1, domain="request", submitted=100):
    """ONE native dispatch of `record`: the receipt, bound before the dispatch, with its prompt domain named."""
    invocation = new_invocation_id()
    record.begin_invocation(invocation, ordinal=ordinal)
    receipt = record.invocation_for(invocation)
    receipt.submitted_tokens = submitted
    receipt.prompt_domain = domain
    return invocation


def _evidence(invocation, **figures):
    """The engine's terminal evidence for one dispatch."""
    payload = {"rid": invocation}
    payload.update(figures)
    return payload


def _store_with(*invocations):
    """A store with ONE request that dispatched the given (domain, figures) pairs."""
    store = TelemetryStore()
    record = RequestRecord("r1")
    record.set_prompt_tokens(rendered=100, submitted=100)
    for index, (domain, submitted, figures) in enumerate(invocations, start=1):
        invocation = _dispatched(record, ordinal=index, domain=domain, submitted=submitted)
        apply_engine(record, _evidence(invocation, **figures), expected_invocation_id=invocation)
    store.add(record.seal("completed", 200, finish_reason="stop"))
    return store, record


class ConcurrentPopulation(unittest.TestCase):
    """F1: the population accounting is REQUEST-LOCAL, and it is idempotent."""

    def test_a_concurrent_request_does_not_account_for_a_failed_one(self):
        """CONCURRENT_POPULATION_WITNESS: the failed request's dispatch is MISSING, not accounted.

        The witness is deterministic: request A blocks inside its sealing while request B runs to completion, and
        A resumes and fails.  The predecessor compared the GLOBAL counters before and after the failure, so B's
        completion was read as A's own progress and A's dispatch was never counted as missing.
        """
        tel = ServerTelemetry()
        a_inside_seal = threading.Barrier(2)
        release_a = threading.Event()

        lost = tel.begin(api="openai", client_request_id="a", model_id="m")
        lost.set_prompt_tokens(rendered=100, submitted=100)
        a_invocation = _dispatched(lost)
        apply_engine(lost, _evidence(a_invocation, matched=90, reused=90, evaluated=10, work=10),
                     expected_invocation_id=a_invocation)

        def blocking_seal(*args, **kwargs):
            # A enters its terminalization and BLOCKS inside the sealing: B runs while A is inside it
            a_inside_seal.wait(timeout=30)
            release_a.wait(timeout=30)
            raise RuntimeError("the seal failed")

        lost.seal = blocking_seal

        def run_a():
            with self.assertRaises(RuntimeError):
                tel.finish(lost, state="completed", http_status=200, finish_reason="stop")

        thread_a = threading.Thread(target=run_a)
        thread_a.start()
        # A is inside its sealing now
        a_inside_seal.wait(timeout=30)

        kept = tel.begin(api="openai", client_request_id="b", model_id="m")
        kept.set_prompt_tokens(rendered=100, submitted=100)
        b_invocation = _dispatched(kept)
        apply_engine(kept, _evidence(b_invocation, matched=90, reused=90, evaluated=10, work=10),
                     expected_invocation_id=b_invocation)
        tel.finish(kept, state="completed", http_status=200, finish_reason="stop")

        # A resumes and its sealing fails
        release_a.set()
        thread_a.join(timeout=30)
        self.assertFalse(thread_a.is_alive(), "the failing request finished")

        counters = tel.store.counters
        self.assertEqual(counters["native_invocations"], 2)
        self.assertEqual(counters["native_invocations_accounted"], 1)
        self.assertEqual(counters["native_invocations_missing"], 1)
        # at quiescence: dispatched = accounted + missing
        self.assertEqual(counters["native_invocations"],
                         counters["native_invocations_accounted"] + counters["native_invocations_missing"])
        # and nothing is left unresolved
        self.assertEqual(counters["native_invocations_unresolved"], 0)

    def test_the_dispatch_population_is_counted_exactly_once(self):
        """DISPATCH_POPULATION_IDEMPOTENCY: the population boundary is idempotent."""
        tel = ServerTelemetry()
        record = tel.begin(api="openai", model_id="m")
        record.set_prompt_tokens(rendered=100, submitted=100)
        _dispatched(record)
        first = tel.store.count_dispatch_population(record)
        second = tel.store.count_dispatch_population(record)
        self.assertEqual(first, 1)
        self.assertEqual(second, 1, "the second count did not count the population again")
        self.assertEqual(tel.store.counters["native_invocations"], 1)

    def test_the_concurrent_accounting_is_the_request_s_own(self):
        """The outcome of one request is never read from another request's counters."""
        tel = ServerTelemetry()
        record = tel.begin(api="openai", model_id="m")
        record.set_prompt_tokens(rendered=100, submitted=100)
        _dispatched(record)
        tel.store.count_dispatch_population(record)
        # a DIFFERENT request completes: its counters must not resolve this request's dispatches
        other = tel.begin(api="openai", model_id="m")
        other.set_prompt_tokens(rendered=100, submitted=100)
        other_invocation = _dispatched(other)
        apply_engine(other, _evidence(other_invocation, matched=90, reused=90, evaluated=10, work=10),
                     expected_invocation_id=other_invocation)
        tel.finish(other, state="completed", http_status=200, finish_reason="stop")
        self.assertEqual(tel.store.counters["native_invocations_accounted"], 1)
        self.assertEqual(tel.store.counters["native_invocations_missing"], 0)
        # this request's own dispatch is still unresolved: its outcome is not known yet
        self.assertEqual(tel.store.counters["native_invocations_unresolved"], 1)

    def test_a_failed_aggregation_commits_nothing(self):
        """A failure inside the aggregation commits no measurement and counts nothing twice.

        ACT-STRATA-TELEMETRY-ATOMIC-STORE-COMMIT-01: the failure comes AFTER the REAL aggregation ran, so the
        rollback is measured against a transaction that really counted something - not against one that failed
        before it counted anything.
        """
        tel = ServerTelemetry()
        record = tel.begin(api="openai", model_id="m")
        record.set_prompt_tokens(rendered=100, submitted=100)
        invocation = _dispatched(record)
        apply_engine(record, _evidence(invocation, matched=90, reused=90, evaluated=10, work=10),
                     expected_invocation_id=invocation)
        original = tel.store._count_locked

        def failing_count(data):
            # the REAL aggregation runs first, and the failure comes after it
            original(data)
            raise RuntimeError("the aggregation failed")

        tel.store._count_locked = failing_count
        with self.assertRaises(RuntimeError):
            tel.finish(record, state="completed", http_status=200, finish_reason="stop")
        tel.store._count_locked = original
        counters = tel.store.counters
        # nothing was committed: no measurement, no accounted invocation
        self.assertEqual(counters["prompt_tokens_evaluated"], 0)
        self.assertEqual(counters["native_invocations_accounted"], 0)
        # the dispatch happened: it stays in the population and it is missing evidence
        self.assertEqual(counters["native_invocations"], 1)
        self.assertEqual(counters["native_invocations_missing"], 1)
        self.assertEqual(counters["native_invocations"],
                         counters["native_invocations_accounted"] + counters["native_invocations_missing"])
        # the record was not kept
        self.assertEqual(tel.store.records, [])
        self.assertEqual(tel.store.bytes, 0)


class RetentionIndependentDomainAuthority(unittest.TestCase):
    """F2: the request's own prompt-domain multiplicity survives the retention."""

    def _dropped(self, keep=1):
        """A store with TWO request-domain dispatches, of which only ONE receipt is retained.

        `keep` says which receipt survives: 0 is the first dispatch's, 1 is the second one's.
        """
        store = TelemetryStore()
        record = RequestRecord("r1")
        record.set_prompt_tokens(rendered=100, submitted=100)
        invocations = []
        for index in range(2):
            invocation = _dispatched(record, ordinal=index + 1, domain="request")
            apply_engine(record, _evidence(invocation, matched=90, reused=90, evaluated=10, work=10),
                         expected_invocation_id=invocation)
            invocations.append(invocation)
        # the retention: the OTHER receipt does not fit and is discarded
        dropped = record.invocation_for(invocations[1 - keep])
        record.invocations.remove(dropped)
        record.invocations_dropped += 1
        self.assertEqual(len(record.invocations), 1, "only one receipt survived the retention")
        store.add(record.seal("completed", 200, finish_reason="stop"))
        return store

    def test_two_request_domain_dispatches_with_the_first_discarded(self):
        """DROPPED_DOMAIN_WITNESS: the surviving receipt is NOT the unique request-domain dispatch."""
        store = self._dropped(keep=1)
        counters = store.counters
        # the request-level coverage is UNAVAILABLE: the prompt was executed twice
        self.assertEqual(counters["prompt_tokens_evaluated"], 0)
        self.assertEqual(counters["prompt_tokens_reused"], 0)
        self.assertEqual(counters["requests_with_complete_accounting"], 0)
        self.assertEqual(counters["requests_with_ambiguous_prompt_coverage"], 1)
        # the cumulative native work of the RECEIPT THAT SURVIVED is still counted
        self.assertEqual(counters["native_positions_evaluated_total"], 10)
        self.assertEqual(counters["native_positions_reused_total"], 90)

    def test_two_request_domain_dispatches_with_the_second_discarded(self):
        """The other order: the FIRST receipt survives and the second one is discarded."""
        store = self._dropped(keep=0)
        counters = store.counters
        self.assertEqual(counters["prompt_tokens_evaluated"], 0)
        self.assertEqual(counters["prompt_tokens_reused"], 0)
        self.assertEqual(counters["requests_with_complete_accounting"], 0)
        self.assertEqual(counters["requests_with_ambiguous_prompt_coverage"], 1)

    def test_retention_does_not_improve_the_certainty(self):
        """Retention must not improve the measurement's certainty: the counts are the same."""
        both, _ = _store_with(("request", 100, {"matched": 90, "reused": 90, "evaluated": 10, "work": 10}),
                              ("request", 100, {"matched": 90, "reused": 90, "evaluated": 10, "work": 10}))
        dropped = self._dropped()
        for counter in ("prompt_tokens_evaluated", "prompt_tokens_reused",
                        "requests_with_complete_accounting", "requests_with_ambiguous_prompt_coverage"):
            self.assertEqual(both.counters[counter], dropped.counters[counter],
                             f"{counter}: discarding a receipt changed the answer")

    def test_one_request_domain_dispatch_and_one_known_continuation(self):
        """ONE request-domain dispatch and one KNOWN continuation: the coverage stays exact."""
        store, _ = _store_with(("request", 100, {"matched": 90, "reused": 90, "evaluated": 10, "work": 10}),
                               ("continuation", 120, {"matched": 120, "reused": 110, "evaluated": 10, "work": 10}))
        counters = store.counters
        self.assertEqual(counters["prompt_tokens_evaluated"], 10)
        self.assertEqual(counters["prompt_tokens_reused"], 90)
        self.assertEqual(counters["requests_with_complete_accounting"], 1)
        # the cumulative native work keeps both invocations
        self.assertEqual(counters["native_positions_evaluated_total"], 20)
        self.assertEqual(counters["native_positions_reused_total"], 200)

    def test_a_discarded_dispatch_whose_domain_cannot_be_established(self):
        """ONE request-domain dispatch and a DISCARDED dispatch whose domain CANNOT be established: refused."""
        store = TelemetryStore()
        record = RequestRecord("r1")
        record.set_prompt_tokens(rendered=100, submitted=100)
        named = _dispatched(record, ordinal=1, domain="request")
        apply_engine(record, _evidence(named, matched=90, reused=90, evaluated=10, work=10),
                     expected_invocation_id=named)
        # a SECOND dispatch whose domain was never named: it could have carried the request's own prompt.
        # Its receipt is discarded, so nothing about it is left to look at.
        unnamed = new_invocation_id()
        record.begin_invocation(unnamed, ordinal=2)
        record.invocation_for(unnamed).submitted_tokens = 100
        record.invocations.remove(record.invocation_for(unnamed))
        record.invocations_dropped += 1
        store.add(record.seal("completed", 200, finish_reason="stop"))
        counters = store.counters
        # the exact request-level coverage is REFUSED: the request's own domain multiplicity is not established
        self.assertEqual(counters["prompt_tokens_evaluated"], 0)
        self.assertEqual(counters["prompt_tokens_reused"], 0)
        self.assertEqual(counters["requests_with_complete_accounting"], 0)

    def test_the_invocation_weighted_ratio_is_preserved(self):
        """The cumulative native work and the invocation-weighted ratio stay valid."""
        store, _ = _store_with(("request", 100, {"matched": 90, "reused": 90, "evaluated": 10, "work": 10}),
                               ("request", 100, {"matched": 90, "reused": 90, "evaluated": 10, "work": 10}))
        reuse = store.summary()["cache_reuse"]
        self.assertEqual(reuse["eligible_invocations"], 2)
        self.assertEqual(reuse["reused_tokens"], 180)
        self.assertEqual(reuse["submitted_tokens"], 200)
        self.assertAlmostEqual(reuse["ratio"], 0.9, places=6)


class OneNormalizedTerminalAuthority(unittest.TestCase):
    """F3: there is ONE authority for the terminal evidence."""

    def _accepted(self, **figures):
        """A record with ONE dispatch whose terminal evidence was already accepted."""
        record = RequestRecord("r1")
        record.set_prompt_tokens(rendered=100, submitted=100)
        invocation = _dispatched(record)
        apply_engine(record, _evidence(invocation, **figures), expected_invocation_id=invocation)
        return record, invocation

    @staticmethod
    def _measurements(receipt):
        """The receipt's MEASUREMENTS - not its diagnostic annotations.

        ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (F3): a diagnostic annotation may be
        recorded separately, but it must not alter the accepted measurement admission.
        """
        data = receipt.to_dict()
        return {section: data[section] for section in ("identity", "state", "prompt", "cache", "timing_ms",
                                                       "generation")}

    def test_a_duplicate_with_a_changed_native_state_is_a_conflict(self):
        """TERMINAL_STATE_DUPLICATE_WITNESS: the effective terminal state is part of the evidence."""
        record, invocation = self._accepted(matched=90, reused=90, evaluated=10, work=10)
        receipt = record.invocation_for(invocation)
        before = self._measurements(receipt)
        verdict = apply_engine(record, _evidence(invocation, matched=90, reused=90, evaluated=10, work=10),
                               expected_invocation_id=invocation, native_state="failed")
        self.assertTrue(verdict.get("conflict"))
        self.assertFalse(verdict.get("admitted"))
        self.assertEqual(self._measurements(receipt), before, "the accepted measurements were changed")
        self.assertEqual(receipt.state, "completed", "the accepted native outcome was changed")

    def test_a_duplicate_with_a_changed_partial_classification_is_a_conflict(self):
        """PARTIAL_CLASSIFICATION_DUPLICATE_WITNESS: the partial classification is part of the evidence."""
        record, invocation = self._accepted(matched=90, reused=90, evaluated=10, work=10)
        receipt = record.invocation_for(invocation)
        before = self._measurements(receipt)
        verdict = apply_engine(record, _evidence(invocation, matched=90, reused=90, evaluated=10, work=10),
                               expected_invocation_id=invocation, native_segment_only=True)
        self.assertTrue(verdict.get("conflict"))
        self.assertFalse(verdict.get("admitted"))
        self.assertEqual(self._measurements(receipt), before, "the accepted measurements were changed")
        self.assertFalse(receipt.native_partial, "the accepted partial classification was changed")

    def test_the_same_outcome_through_the_error_path_is_an_identical_duplicate(self):
        """The production error path and the DONE path agree: the same outcome is a duplicate."""
        record, invocation = self._accepted(matched=90, reused=90, evaluated=10, work=10)
        receipt = record.invocation_for(invocation)
        before = self._measurements(receipt)
        verdict = apply_engine(record, _evidence(invocation, matched=90, reused=90, evaluated=10, work=10),
                               expected_invocation_id=invocation, native_state="completed")
        self.assertTrue(verdict.get("duplicate"))
        self.assertTrue(verdict.get("admitted"))
        self.assertEqual(self._measurements(receipt), before)

    def test_an_identical_complete_duplicate_is_a_duplicate(self):
        """The identical duplicate is not a conflict."""
        record, invocation = self._accepted(matched=90, reused=90, evaluated=10, work=10, lookup_ms=12.0)
        receipt = record.invocation_for(invocation)
        before = self._measurements(receipt)
        verdict = apply_engine(record, _evidence(invocation, matched=90, reused=90, evaluated=10, work=10,
                                                 lookup_ms=12.0),
                               expected_invocation_id=invocation)
        self.assertTrue(verdict.get("duplicate"))
        self.assertFalse(verdict.get("conflict"))
        self.assertEqual(self._measurements(receipt), before)
        self.assertEqual(receipt.correlation, "verified")

    def test_the_native_outcome_is_not_the_http_outcome(self):
        """The native outcome and the HTTP outcome stay apart."""
        record, invocation = self._accepted(matched=90, reused=90, evaluated=10, work=10)
        receipt = record.invocation_for(invocation)
        self.assertEqual(receipt.state, "completed")
        # the HTTP request failed afterwards: the native outcome is not rewritten
        record.seal("failed", 500, finish_reason="error")
        self.assertEqual(receipt.state, "completed")


class SchemaResourceIdentity(unittest.TestCase):
    """F5: the historical v2 contract and the current v3 contract have their OWN resource identities."""

    def test_the_schema_ids_are_distinct(self):
        """DISTINCT_SCHEMA_IDS: the two contracts are two resources."""
        from serve.reqtelemetry.schema import SCHEMA_V2, SCHEMA_V3
        self.assertNotEqual(SCHEMA_V2["$id"], SCHEMA_V3["$id"])
        self.assertTrue(SCHEMA_V2["$id"].endswith("strata-request-telemetry-2.json"),
                        f"the historical id is the v2 resource: {SCHEMA_V2['$id']}")
        self.assertTrue(SCHEMA_V3["$id"].endswith("strata-request-telemetry-3.json"),
                        f"the current id is the v3 resource: {SCHEMA_V3['$id']}")

    def test_each_schema_matches_its_file(self):
        """Each schema is the contract that is on disk."""
        import json
        from pathlib import Path
        from serve.reqtelemetry.schema import SCHEMA_V2, SCHEMA_V3
        # the schema files live in the repository's docs/, above terminal/ (the serving layer's root).
        root = Path(__file__).resolve().parents[2]
        v2 = json.loads((root / "docs/telemetry/strata-request-telemetry-2.schema.json").read_text())
        v3 = json.loads((root / "docs/telemetry/strata-request-telemetry-3.schema.json").read_text())
        self.assertEqual(v2, SCHEMA_V2)
        self.assertEqual(v3, SCHEMA_V3)

    def test_the_records_validate_against_their_own_version(self):
        """A historical record validates against v2; a current record validates against v3."""
        import json
        from pathlib import Path
        from serve.reqtelemetry import ServerTelemetry, validate
        from serve.reqtelemetry.schema import SCHEMA_V2, SCHEMA_V3
        # the fixture sits beside the serving layer's own files (terminal/serve/fixtures/).
        root = Path(__file__).resolve().parents[1]
        historical = json.loads((root / "serve/fixtures/telemetry/record-v2.json").read_text())
        self.assertEqual(validate(historical, SCHEMA_V2), [])
        self.assertTrue(validate(historical, SCHEMA_V3),
                        "the historical record does not validate against the current contract")
        tel = ServerTelemetry()
        record = tel.begin(api="openai", client_request_id="abc", model_id="m")
        record.set_prompt_tokens(rendered=100, submitted=100)
        invocation = _dispatched(record)
        apply_engine(record, _evidence(invocation, matched=90, reused=90, evaluated=10, work=10),
                     expected_invocation_id=invocation)
        current = tel.finish(record, state="completed", http_status=200, finish_reason="stop")
        self.assertEqual(validate(current, SCHEMA_V3), [])
        self.assertTrue(validate(current, SCHEMA_V2),
                        "the current record does not validate against the historical contract")
