# 08 - The build and the platform matrix

| What | Where | Result |
|---|---|---|
| the native encoder's test (no CUDA) | `g++ -std=c++20 -Iinclude src/program/reqtelemetry_test.cpp` | all checks passed, exit 0 |
| the native writer/reader roundtrip (no CUDA) | `src/program/reqtelemetry_roundtrip.cpp` + `tools/test_reqtelemetry_roundtrip.py` | builds; 6 tests, OK |
| the CUDA engine (SM61, SM120) | `cmake -DSTRATA_ENABLE_CUDA=ON` | **NOT_EXECUTED**: this host has no CUDA toolkit and no GPU |
| the native cache controls (T01-T07, T13, T14) | the live engine | **NOT_EXECUTED**: no engine to run them on |
| the performance parity | the two arms on a GPU | **NOT_EXECUTED**: no GPU here |

The amendment changes **no** native source: `include/strata/program/reqtelemetry.hpp`, `src/program/generate.cpp`
and the two native test programs are byte-identical to the entry commit. What the amendment changed is on the
server's side and in the exporter, so the native build is not affected by it - but it was not run here either, and
that is stated rather than assumed.

## The native source authority (G8)

The predecessor's production diff in `src/program/generate.cpp` is published in this package as
`native-diff.txt` (`git diff c45ec828..HEAD -- src/program/generate.cpp include/strata/program/reqtelemetry.hpp`),
so the review can read it: the GEN and GENI parsing, the batch execution paths, the identity propagation, the DONE
and BDONE ownership, the cache selection boundaries, the checkpoint restoration outcome, the replay accounting,
the cancellation paths and the telemetry-disabled protocol compatibility.

The native accounting is attached to the execution decisions (`matched`/`reused`/`evaluated`/`work` are filled in
the engine's request loop from the cache diagnostics' own comparison and the state restoration's outcome), not
derived from the aggregate timing figures. The native part was **not** re-qualified here: the encoder's own test
and the roundtrip pass, and the live controls remain NOT_EXECUTED.
