# 07 - The security and the privacy

Nothing of the amendment widens the surface:

* the record is still **metadata only**: no prompt, no answer, no reasoning, no tool arguments, no header, no
  key, no raw token id, no prompt hash. The privacy witness of the predecessor
  (`serve/test_reqtelemetry.py: Evidence.test_the_evidence_carries_no_content`) checks the record's key list;
  the amendment adds exactly one key to that list - `accounting`, which holds a state word and a list of problem
  strings - and the check still passes.
* the request-level endpoints still **fail closed** when the listener is not this PC's own loopback and there
  is no API key (`serve/server.py: _telemetry_allowed`).
* the **no-store** headers on the request-level responses are untouched.
* the filters and the cursors are **validated** now (G7), so a malformed input is a 400 with a message instead of
  a silent empty page.
* the telemetry stays **independent** of the content-capturing API monitor: the record's own monotonic clock and
  the handler's own status are used, not the monitor's record (the monitor may be off, and the telemetry does not
  depend on it).
* with the telemetry off nothing is allocated and nothing is sent to the engine: no receipt, no evidence writer,
  no `rid=` on the GEN line.

The amendment does not touch the authentication, the CORS rules, the ports or the ingress.
