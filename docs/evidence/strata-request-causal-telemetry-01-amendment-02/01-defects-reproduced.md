# 01 - The defects, reproduced against the entry head

Every defect below was reproduced against `579f5cef` before it was corrected.  The reproduction is the witness that
now guards the correction (the "witness" column names it), run against the entry head.

| # | The defect | How it showed itself at the entry head | The witness that guards it now |
|---|---|---|---|
| G1 | the store counted measurements that were invalid, unattributed or out of a broken accounting | a record with `submitted 100, matched 100, reused 120, evaluated 0` added 120 to `prompt_tokens_reused`; `reused -5` ADDED 5 to the counter (the counter fell); `reused 90, evaluated 8` (the sum does not close) was counted; a record whose engine receipt carried no id was counted as authoritative | `serve/test_telemetry_amendment02.py` `Admission` |
| G2/A2 | the receipt was bound to the REQUEST, not to the invocation | the ordinal was appended to the id after the execution (`f"{id}#{n}"`), so the id the engine echoed was not an invocation identity; a receipt of another invocation could not be told apart from this request's own | `InvocationIdentity` (the recovery witness: request A, invocations B and C, the receipt of B arrives during C) |
| G3 | the native cumulative work was the distinct count | `tele.work = tele.evaluated` on every path, including the re-read path, where the positions read before are evaluated a second time | the native diff (`04-native-production.diff`), `NOT_EXECUTED` on this host |
| G4 | the native terminal error carried no evidence | the checkpoint-restore failure printed a bare `ERR restoring a conversation checkpoint failed` and returned: the measurement it had made (the attempt, the duration) was lost | the native diff; the server side reads the ERR line's telemetry (`parse_error_figures`) |
| G5 | the engine's eviction counter could lower the total | a reading of 10 then 8 then 11 gave 10, 13, 16: the high-water mark was overwritten by the smaller reading | `Monotonicity` (10, 8, 11 -> 10, 10, 11) |
| G6 | a cursor that names nothing was accepted | a cursor without an owner, with a zero or negative sequence, or dated in the future was accepted | `Cursors` and the HTTP endpoint (`/v1/telemetry/requests?cursor=...` answers 400) |
| A1 | the queue wait was overwritten with the whole request time | `Service.run` measured the wait when the request took its turn and `_finish_telemetry` replaced it with `perf_counter() - waiting` | `HttpWitnesses.test_the_queue_wait_is_the_wait_and_not_the_whole_request` |
| A3 | the first token was the generation loop's, and the emitted count was its counter | the timestamp was taken in the Service loop, before the response was serialized and written; `emitted = n` was the loop's token counter | `HttpWitnesses.test_the_first_content_is_timed_at_the_write_boundary` |
| A4 | the accepted count and the terminal count came from the same insertion | a record that could not be sealed or stored vanished from both counters: the identity balanced because nothing was counted at all | `Lifecycle.test_the_terminal_outcome_survives_a_seal_that_fails` |
| A5 | the evidence writer's bounds and its flush were inexact | `flush()` returned true while a detached record was blocked in the writer; the byte budget counted CHARACTERS; the record being written was outside the bound; the handle could be closed while the worker still used it; a refused write was not counted | `EvidenceWriter` (four witnesses) |
| A7 | the browser's accounting bar drew more than the numbers support | the denominator was `reused + evaluated`, an unknown replay became a measured zero, and a violated accounting still got a normalized bar | `tools/test_telemetry_web_accounting.py` (four presentation cases) |
| A8 | the process-lifetime totals were relabelled when the model changed | every `strata_*` telemetry metric carried `model_name="<the model selected at scrape time>"` | `ModelSwitch` |
| A9 | a batch slot's admission segment was published as the whole invocation | `_apply_bdone` put the slot's figures into `self.last` without saying that they describe the slot's ADMISSION segment | the server marks the receipt as a segment (`native_partial`) and keeps it out of the authoritative totals |

The predecessor's expectations that these defects contradict were changed, and only where the amendment demands it:
the canonical telemetry metrics no longer carry a model label (A8), the emitted-token count is null with a reason
(A3), and the two records that were built by hand instead of through the engine's receipt now go through the
production path (`apply_engine`) so that they are correlated measurements (G1).
