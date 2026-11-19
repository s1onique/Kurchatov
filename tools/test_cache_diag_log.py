"""The server reads the engine's STRATA_CACHE_DIAG events from its log: the parsing, the fields, and the
no-user-data rule.  No GPU, no engine, no server: a log file with the engine's lines in it.

The two pieces under test (ConvCacheLog and conversation_cache_view) are taken from serve/server.py by source, so
the test needs none of the server's other imports (jinja2 and the rest): it runs on a bare Python.

Run: python3 tools/test_cache_diag_log.py
"""
import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]


def load_from_server(names):
    """The named top-level definitions of serve/server.py, taken from its source: no imports of their own, so the
    test does not need the server's dependencies."""
    source = (ROOT / 'serve' / 'server.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    wanted = set(names)
    module = ast.Module(body=[], type_ignores=[])
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in wanted:
            module.body.append(node)
    namespace = {'re': __import__('re'), 'os': os, 'time': __import__('time')}
    exec(compile(module, str(ROOT / 'serve' / 'server.py'), 'exec'), namespace)
    return namespace


_NS = load_from_server(['ConvCacheLog', 'conversation_cache_view'])
ConvCacheLog = _NS['ConvCacheLog']
conversation_cache_view = _NS['conversation_cache_view']


DIAG_LINE = ("STRATA_CACHE_DIAG event=decision request_seq=7 prompt_tokens=1200 selected_source=active_checkpoint "
             "selected_prefix_tokens=900 candidate_count=4 max_candidate_prefix_tokens=1024 "
             "longest_common_prefix_tokens=900 first_mismatch_position=-1 rejection_reason=EXACT_MATCH "
             "deeper_rejection_reason=IMAGE_MISMATCH deeper_candidate_tokens=6000 "
             "cache_parked_entries=2 cache_parked_bytes=3145728 cache_evictions_total=1 "
             "subject_tokens=0 subject_serial=-1")


def write_log(lines):
    handle = tempfile.NamedTemporaryFile('w', suffix='.log', delete=False)
    try:
        for line in lines:
            handle.write(line + '\n')
    finally:
        handle.close()
    return handle.name


class CacheDiagLogTest(unittest.TestCase):
    def test_a_diagnostic_line_is_read(self):
        path = write_log([DIAG_LINE])
        try:
            log = ConvCacheLog()
            log.poll(path, 0)
            self.assertEqual(len(log.diag), 1, 'the diagnostic line was read')
            event = log.diag[0]
            self.assertEqual(event['event'], 'decision')
            self.assertEqual(event['request_seq'], 7)
            self.assertEqual(event['prompt_tokens'], 1200)
            self.assertEqual(event['selected_source'], 'active_checkpoint')
            self.assertEqual(event['selected_prefix_tokens'], 900)
            self.assertEqual(event['candidate_count'], 4)
            self.assertEqual(event['max_candidate_prefix_tokens'], 1024)
            self.assertEqual(event['longest_common_prefix_tokens'], 900)
            self.assertEqual(event['first_mismatch_position'], -1)
            self.assertEqual(event['rejection_reason'], 'EXACT_MATCH')
            self.assertEqual(event['deeper_rejection_reason'], 'IMAGE_MISMATCH')
            self.assertEqual(event['deeper_candidate_tokens'], 6000)
            self.assertEqual(event['cache_parked_entries'], 2)
            self.assertEqual(event['cache_parked_bytes'], 3145728)
            self.assertEqual(event['cache_evictions_total'], 1)
        finally:
            os.unlink(path)

    def test_the_conversation_cache_lines_still_work(self):
        path = write_log([
            'strata serve: conversation cache: parked 512 tokens in 12.3 ms; parked=1 bytes=4096 evictions=0 '
            'snapshot_bytes=4096 reused_kv_bytes=0',
            DIAG_LINE,
            'strata serve: conversation cache: restored 900 tokens (checkpoint) in 8.1 ms; parked=1 bytes=4096',
        ])
        try:
            log = ConvCacheLog()
            state = log.poll(path, 0)
            self.assertEqual(state['parks'], 1, 'the park was counted')
            self.assertEqual(state['restores'], 1, 'the restore was counted')
            self.assertEqual(state['parked'], 1, 'the parked count is read')
            self.assertEqual(len(log.diag), 1, 'the diagnostic line was read as well')
        finally:
            os.unlink(path)

    def test_the_events_are_bounded(self):
        lines = []
        for i in range(200):
            lines.append(DIAG_LINE.replace('request_seq=7', f'request_seq={i}'))
        path = write_log(lines)
        try:
            log = ConvCacheLog()
            log.poll(path, 0)
            self.assertLessEqual(len(log.diag), ConvCacheLog.DIAG_KEEP, 'the kept events are bounded')
            self.assertEqual(log.diag_counts.get('decision'), 200, 'the counts are not bounded away')
        finally:
            os.unlink(path)

    def test_no_user_data(self):
        # a sentinel in the prompt would never be written by the engine; the reader must not invent one either
        path = write_log([DIAG_LINE])
        try:
            log = ConvCacheLog()
            log.poll(path, 0)
            blob = repr(log.diag)
            self.assertNotIn('987654', blob, 'no token id in the parsed events')
            for key in log.diag[0]:
                self.assertIsInstance(log.diag[0][key], (int, str), 'the fields are counts and words')
        finally:
            os.unlink(path)

    def test_the_metrics_view_carries_the_events(self):
        path = write_log([DIAG_LINE])
        try:
            log = ConvCacheLog()
            parked = log.poll(path, 0)
            view = conversation_cache_view({'conversation_cache_mib': 1024, 'conversation_cache_slots': 4},
                                           [], {}, parked, log.diag, log.diag_counts)
            self.assertEqual(len(view['diagnostics']), 1, 'the events are in the view')
            self.assertEqual(view['diagnostic_counts'].get('decision'), 1, 'the counts are in the view')
            self.assertEqual(view.get('diagnostic_lost'), 0, 'nothing was lost')
            self.assertFalse(view.get('diagnostic_truncated'), 'the window was not truncated')
        finally:
            os.unlink(path)

    def test_the_metrics_view_says_when_records_were_lost(self):
        """R3: the view's counts must not be presented as comprehensive when records were passed over."""
        lines = []
        for i in range(8000):
            lines.append(DIAG_LINE.replace('request_seq=7', f'request_seq={i}'))
        path = write_log(lines)
        try:
            log = ConvCacheLog()
            parked = log.poll(path, 0)
            view = conversation_cache_view({'conversation_cache_mib': 1024, 'conversation_cache_slots': 4},
                                           [], {}, parked, log.diag, log.diag_counts,
                                           log.diag_lost, log.diag_truncated)
            self.assertTrue(view.get('diagnostic_truncated'), 'the view says the window was truncated')
            self.assertGreater(view.get('diagnostic_lost', 0), 0, 'the view says how many were lost')
        finally:
            os.unlink(path)

    def test_without_the_switch_nothing_changes(self):
        # a log without any diagnostic line: the view is the one from before
        path = write_log(['strata serve: conversation cache: parked 512 tokens in 12.3 ms; parked=1 bytes=4096 '
                           'evictions=0 snapshot_bytes=4096 reused_kv_bytes=0'])
        try:
            log = ConvCacheLog()
            parked = log.poll(path, 0)
            view = conversation_cache_view({'conversation_cache_mib': 1024, 'conversation_cache_slots': 4},
                                           [], {}, parked, log.diag, log.diag_counts)
            self.assertEqual(view['diagnostics'], [], 'no events')
            self.assertEqual(view['parked'], 1, 'the parked count is still read')
        finally:
            os.unlink(path)

    def test_more_than_the_read_window_between_two_polls_loses_records(self):
        """R3: the reader's window is 1 MiB.  When more than that arrives between two polls, the older lines are
        passed over.  The counts must say so: without a loss signal they cannot be described as comprehensive."""
        # each line is about 300 bytes, so 8000 lines are well over the 1 MiB window
        lines = []
        for i in range(8000):
            lines.append(DIAG_LINE.replace('request_seq=7', f'request_seq={i}'))
        path = write_log(lines)
        try:
            log = ConvCacheLog()
            log.poll(path, 0)
            # the reader did read what it could: the last events are there
            self.assertGreater(len(log.diag), 0, 'the reader read the tail of the log')
            # but the earlier records were passed over: the loss must be DETECTABLE
            self.assertTrue(getattr(log, 'diag_lost', 0) > 0,
                            'the reader says that records were lost between the polls')
            self.assertTrue(getattr(log, 'diag_truncated', False),
                            'the reader says that its window was truncated')
            # and the counts must not claim to be complete
            self.assertLess(log.diag_counts.get('decision', 0), 8000,
                            'the count is smaller than the number of events written')
        finally:
            os.unlink(path)

    def test_a_small_log_reports_no_loss(self):
        """R3b: the loss signal must not fire when nothing was lost."""
        path = write_log([DIAG_LINE, DIAG_LINE])
        try:
            log = ConvCacheLog()
            log.poll(path, 0)
            self.assertEqual(getattr(log, 'diag_lost', 0), 0, 'nothing was lost')
            self.assertFalse(getattr(log, 'diag_truncated', False), 'the window was not truncated')
            self.assertEqual(log.diag_counts.get('decision'), 2, 'both events were counted')
        finally:
            os.unlink(path)

    def test_the_engine_writes_what_the_reader_reads(self):
        """The engine's writer and the server's reader agree: the line the C++ writer produces is the line the
        Python reader parses.  The C++ side is built from the repository's own header, so the two cannot drift."""
        root = ROOT
        source = root / 'src' / 'program' / 'cache_diag_roundtrip.cpp'
        if not source.exists():
            self.skipTest('the round-trip program is not in this tree')
        binary = Path(tempfile.mkdtemp()) / 'roundtrip'
        build = subprocess.run(['clang++', '-std=c++20', '-O2', f'-I{root / "include"}',
                                str(source), '-o', str(binary)], capture_output=True, text=True)
        self.assertEqual(build.returncode, 0, f'the round-trip program builds: {build.stderr}')
        # with the switch off: nothing is written
        off = subprocess.run([str(binary)], capture_output=True, text=True)
        self.assertEqual(off.stdout.strip(), 'enabled=0', 'the switch is off by default')
        self.assertEqual(off.stderr.strip(), '', 'nothing is written with the switch off')
        # with the switch on: one line, and the reader reads it
        on = subprocess.run([str(binary)], capture_output=True, text=True,
                            env={**os.environ, 'STRATA_CACHE_DIAG': '1'})
        self.assertEqual(on.stdout.strip(), 'enabled=1', 'the switch turns the diagnostics on')
        self.assertTrue(on.stderr.startswith('STRATA_CACHE_DIAG event=decision '), 'the event line is written')
        path = write_log([on.stderr.strip()])
        try:
            log = ConvCacheLog()
            log.poll(path, 0)
            self.assertEqual(len(log.diag), 1, 'the reader read the engine line')
            self.assertEqual(log.diag[0]['selected_source'], 'live', 'the source survived the round trip')
            self.assertEqual(log.diag[0]['selected_prefix_tokens'], 60, 'the prefix survived the round trip')
            self.assertEqual(log.diag[0]['rejection_reason'], 'EXACT_MATCH', 'the reason survived the round trip')
            self.assertEqual(log.diag[0]['longest_common_prefix_tokens'], 60, 'the common prefix survived')
            self.assertIn('deeper_rejection_reason', log.diag[0], 'the deeper refusal is a field of the event')
            self.assertEqual(log.diag[0]['deeper_rejection_reason'], 'UNKNOWN',
                             'the round-trip program has no deeper refusal, so the field says UNKNOWN')
        finally:
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
