# 02 - The field-by-field wiring matrix (G4)

Every field of the canonical record, the production writer that fills it, the authority, the boundary where it is
measured, whether it applies, and the witness that proves it.

| FIELD | PRODUCTION_WRITER | MEASUREMENT_AUTHORITY | MEASUREMENT_BOUNDARY | APPLICABILITY | EXECUTABLE_WITNESS |
|---|---|---|---|---|---|
| `identity.request_id` | `serve/reqtelemetry/record.py: new_request_id()` | HTTP server | the record's creation | always | `Correlation.test_two_physical_requests_with_the_same_client_id_are_two_records` |
| `identity.client_request_id` | `serve/server.py: do_POST` | HTTP server | the request's header | when the client sent a valid one | `serve/test_reqtelemetry.py: Record.test_the_client_id_is_validated` |
| `identity.engine_instance_id` | `serve/server.py: Service.prepare` | HTTP server | after the model was selected | always | `ProductionWiring.test_the_native_measurements_reach_the_record_through_the_real_parser` |
| `identity.server_instance_id` | `serve/reqtelemetry/server.py: ServerTelemetry.begin` | HTTP server | the process's start | always | `serve/test_reqtelemetry.py` |
| `identity.engine_invocation_id` | `serve/reqtelemetry/correlation.py: apply_engine` | native engine (the echoed `rid`) | the DONE line | when the engine echoes the id | `Correlation.test_a_matching_id_is_applied`, `..._a_missing_id_leaves_the_correlation_unavailable` |
| `identity.slot_id` | `serve/reqtelemetry/correlation.py: apply_engine` | native engine | the DONE line | when the engine ran in a slot | `ProductionWiring.test_the_native_measurements_reach_the_record_through_the_real_parser` |
| `identity.model_id` | `serve/server.py: Service.prepare` | HTTP server | after the model was selected | always | `ProductionWiring.test_the_requested_and_the_effective_budget_are_different_numbers` |
| `identity.build_revision` | `serve/server.py: Service.prepare` | HTTP server | after the model was selected | when the engine reports a commit | as above |
| `lifecycle.state` | `serve/server.py: Service._seal_telemetry` | HTTP server | the request's end | always | `LifecycleOwnership.test_a_refused_request_still_gets_a_receipt` |
| `lifecycle.http_status` | `serve/server.py: the handler's `send_response` | HTTP server | the response's status line | always | `LifecycleOwnership.test_a_refused_request_still_gets_a_receipt` |
| `lifecycle.finish_reason` | `serve/server.py: Service._finish_telemetry` | native engine | the DONE line | always | `serve/test_reqtelemetry.py: Cancelled` |
| `prompt.rendered_tokens` | `serve/server.py: Service.prepare` | HTTP server | after the template and the tokenization | always | `ProductionWiring.test_the_rendered_prompt_and_the_submitted_one_are_different_numbers` |
| `prompt.submitted_tokens` | `serve/server.py: Service._finish_telemetry` | HTTP server | the engine's admission | always | as above |
| `prompt.matched_prefix_tokens` | `serve/reqtelemetry/correlation.py: apply_engine` | native engine | the cache lookup | when the engine measured it | `serve/test_reqtelemetry.py: EngineFigures` |
| `prompt.reused_prefix_tokens` | `serve/reqtelemetry/correlation.py: apply_engine` | native engine | the state restoration | when the engine measured it | `NullSemantics.test_a_null_reuse_is_not_a_zero` |
| `prompt.evaluated_tokens` | `serve/reqtelemetry/correlation.py: apply_engine` | native engine | the prefill | when the engine measured it | `NullSemantics.test_the_non_closing_accounting_is_reported` |
| `prompt.replayed_tokens` | `serve/reqtelemetry/correlation.py: apply_engine` | native engine | the prefill | when the engine measured it | `serve/test_reqtelemetry.py: EngineFigures` |
| `prompt.non_prefix_reused_tokens` | `serve/reqtelemetry/record.py: seal` | structural (Strata reuses a contiguous prefix only) | the record's end | always, once a reuse was measured | `NullSemantics.test_the_non_prefix_reuse_is_a_documented_structural_zero` |
| `prompt.evaluation_work_tokens` | `serve/reqtelemetry/correlation.py: apply_engine` | native engine | the prefill | when the engine measured it | `serve/test_reqtelemetry.py` |
| `prompt.first_divergent_token_index` | `serve/reqtelemetry/correlation.py: apply_engine` | native engine | the comparison | when the engine compared | `serve/test_reqtelemetry.py` |
| `cache.source`, `cache.reason_code`, `cache.restore_*`, `cache.invalidations`, `cache.evictions` | `serve/reqtelemetry/correlation.py: apply_engine` | native engine | the DONE line | when the engine reported them | `serve/test_reqtelemetry.py: EngineFigures` |
| `cache.disposition` | `serve/reqtelemetry/accounting.py: derive_disposition` | derived from the engine's evidence | the record's end | always | `NullSemantics` (three tests) |
| `timing_ms.tokenization` | `serve/server.py: Service.prepare` | HTTP server (monotonic) | the encode | always | `ProductionWiring.test_the_durations_come_from_a_monotonic_clock` |
| `timing_ms.template_render` | - | - | - | **null**: the render and the tokenization are one pass | `measurement_quality.unavailable_fields` says why |
| `timing_ms.queue` | `serve/server.py: Service.run` | HTTP server (monotonic) | the turn's acquisition | always | `ProductionWiring.test_the_durations_come_from_a_monotonic_clock` |
| `timing_ms.prefill_wall`, `timing_ms.decode_wall` | `serve/server.py: Service._finish_telemetry` | native engine | the DONE line | when the engine measured them | `serve/test_reqtelemetry.py` |
| `timing_ms.http_first_token` | `serve/server.py: Service._finish_telemetry` | HTTP server (monotonic) | the first TOKEN the client saw | when a token was produced | `ProductionWiring` |
| `timing_ms.total` | `serve/server.py: Service._seal_telemetry` | HTTP server (monotonic) | the request's admission to its end | always | `ProductionWiring.test_the_durations_come_from_a_monotonic_clock` |
| `generation.requested_max_output_tokens` | `serve/server.py: Service.prepare` | HTTP server | the client's request | when the client asked for a limit | `ProductionWiring.test_the_requested_and_the_effective_budget_are_different_numbers` |
| `generation.effective_max_output_tokens` | `serve/server.py: Service.prepare` | HTTP server | the context's room | always | as above |
| `generation.generated_tokens` | `serve/server.py: Service._finish_telemetry` | native engine | the DONE line | when the engine counted | `ProductionWiring.test_the_generated_and_the_emitted_tokens_are_different_numbers` |
| `generation.emitted_tokens` | `serve/server.py: Service._finish_telemetry` | HTTP server | the tokens the client received | always | as above |
| `generation.speculative_*` | `serve/reqtelemetry/correlation.py` / `_finish_telemetry` | native engine | the DONE line | when the engine reported them | `serve/test_reqtelemetry.py` |
| `measurement_quality.accounting` | `serve/reqtelemetry/accounting.py` | derived | the record's end | always | `NullSemantics.test_the_accounting_is_published_in_the_record` |
