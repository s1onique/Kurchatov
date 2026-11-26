# 05 - The suite results, side by side

Both runs use the **same** environment (the local-only `regex` stand-in of 00-entry-state.md), so they are
comparable. The baseline is the entry commit in its own worktree (`/tmp/kurchatov-base`).

| | Baseline (ENTRY_HEAD `c45ec828`) | The corrected tree |
|---|---|---|
| the whole server suite | `Ran 1054 tests in 342.476s` - 3 failures, 6 errors, 23 skipped | `Ran 1092 tests in 363.131s` - 3 failures, 6 errors, 23 skipped |
| the failures | the nine of the `regex` stand-in | **the same nine** - no new failure |

## The baseline

```
Ran 1054 tests in 342.476s
FAILED (failures=3, errors=6, skipped=23)
```

The nine failures are the ones the `regex` stand-in causes (the tokenizer's pre-tokenizer is a different one):

```
ERROR: test_a_body_that_comes_in_drops_does_not_hold_the_connection (test_server.AnswerBeforeTheBody)
ERROR: test_a_special_token_decodes_to_its_text (test_dsv4.PreTokenizer)
ERROR: test_digits_then_ideographs_then_the_rest (test_dsv4.PreTokenizer)
ERROR: test_digits_then_ideographs_then_words_cut_where_capitals_end (test_flint.PreTokenizer)
ERROR: test_one_request_with_more_than_64_images_keeps_all_its_files (test_server.VisionCacheEviction)
ERROR: test_plain_encode_still_evicts_the_oldest (test_server.VisionCacheEviction)
FAIL:  test_digits_in_runs_of_three (test_glm.PreTokenizer)
FAIL:  test_pieces_and_whole_tokens (test_lfm2.PreTokenizer)
FAIL:  test_server_close_ends_the_sampler (test_responses.NoLeakedSampler)
```

The predecessor's own evidence shows the same suite passing **with the real wheel** (1 054 tests, 23 skipped,
no failures), so these nine are an artefact of the stand-in and not a property of the tree.

## The corrected tree

The run is in `suite-output.txt` (every failure of the run and its tail).  The 38 extra tests are the amendment's
own witnesses (`serve/test_telemetry_integrity.py`).

## What the comparison says

The corrected tree has **no failure that the baseline does not have**. The telemetry's own suites (87 tests) and
the mutation witnesses (8) pass on the corrected tree and fail on the entry commit.
