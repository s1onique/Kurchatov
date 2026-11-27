"""The web app's identity: Kurchatov's name, and the build identifier that names the DEPLOYED artifact.

No GPU, no engine, no server: the deployed artifact's BUILD.json beside a fake executable, and the server's
own reader taken from serve/server.py by source.

What it checks:
  * the browser title and the header brand say Kurchatov;
  * the standalone monitor's title and brand say Kurchatov;
  * the upstream reference, the API-compatible config filename and the model names are PRESERVED;
  * the build identifier comes from the DEPLOYED artifact's BUILD.json - and is ABSENT (never invented)
    when the artifact does not carry it.

Run: python3 tools/test_kurchatov_identity.py
"""
import ast
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]


def load_from_server(names):
    """The named top-level definitions of serve/server.py, taken from its source: no imports of their own, so the
    test does not need the server's dependencies."""
    source = (ROOT / 'terminal' / 'serve' / 'server.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    wanted = set(names)
    module = ast.Module(body=[], type_ignores=[])
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in wanted:
            module.body.append(node)
    namespace = {'json': json, 'os': os}
    exec(compile(module, str(ROOT / 'terminal' / 'serve' / 'server.py'), 'exec'), namespace)
    return namespace


_NS = load_from_server(['build_identity'])
build_identity = _NS['build_identity']


INDEX = (ROOT / 'terminal' / 'serve' / 'web' / 'index.html').read_text(encoding='utf-8')
MONITOR = (ROOT / 'terminal' / 'serve' / 'web' / 'monitor.html').read_text(encoding='utf-8')
APP_JS = (ROOT / 'terminal' / 'serve' / 'web' / 'app.js').read_text(encoding='utf-8')
MONITOR_JS = (ROOT / 'terminal' / 'serve' / 'web' / 'monitor.js').read_text(encoding='utf-8')
SERVER = (ROOT / 'terminal' / 'serve' / 'server.py').read_text(encoding='utf-8')


class KurchatovIdentityTest(unittest.TestCase):
    def test_the_name_is_kurchatov(self):
        self.assertIn('<title>Kurchatov</title>', INDEX, 'the browser title names Kurchatov')
        self.assertIn('<span class="st-header__brand">Kurchatov</span>', INDEX,
                      'the header brand names Kurchatov')
        self.assertNotIn('<title>PolyStrata</title>', INDEX, 'the old title is gone')
        self.assertNotIn('st-header__brand">PolyStrata', INDEX, 'the old brand is gone')

    def test_the_standalone_monitor_is_kurchatov(self):
        self.assertIn('<title>Kurchatov API Monitor</title>', MONITOR, "the monitor's title names Kurchatov")
        self.assertIn('<div class="brand">Kurchatov <span>Local inference</span>', MONITOR,
                      "the monitor's brand names Kurchatov")
        self.assertNotIn('PolyStrata API Monitor', MONITOR, 'the old monitor title is gone')
        self.assertNotIn('class="brand">PolyStrata', MONITOR, 'the old monitor brand is gone')

    def test_the_upstream_and_the_api_are_preserved(self):
        # the upstream project is still credited, and its link still works
        self.assertIn('https://github.com/VecSzn/PolyStrata', INDEX, 'the upstream link is preserved')
        self.assertIn('PolyStrata on GitHub', INDEX, 'the upstream link text is preserved')
        # the run config's file name is part of the API: it must not change
        self.assertIn('strata-&lt;model&gt;.json', INDEX, "the config file name is preserved")
        # the monitor's tagline and the app's storage keys are untouched
        self.assertIn('Local inference', MONITOR, "the monitor's tagline is preserved")
        self.assertIn('localStorage.getItem("strata.theme")', INDEX, "the app's storage keys are preserved")

    def test_the_build_identifier_comes_from_the_deployed_artifact(self):
        # the server reads the BUILD.json beside the RUNNING executable
        self.assertIn('"BUILD.json"', SERVER, 'the server reads the artifact BUILD.json')
        self.assertIn('build_commit', SERVER, 'the server reads the artifact commit')
        self.assertIn('build_backend', SERVER, 'the server reads the artifact backend')
        self.assertIn('build_cuda', SERVER, 'the server reads the artifact CUDA version')
        # and the web app renders exactly that
        self.assertIn('renderBuildId', APP_JS, 'the app renders the build identifier')
        self.assertIn('id="build-id"', INDEX, 'the app has the build identifier element')
        self.assertIn('id="build-id"', MONITOR, 'the monitor has the build identifier element')
        self.assertIn('status.build', MONITOR_JS, 'the monitor reads the build identity from the status')

    def test_the_identifier_is_absent_when_the_artifact_does_not_carry_it(self):
        # no BUILD.json facts: nothing is shown, and nothing is invented
        self.assertEqual(build_identity({}), {'commit': None, 'backend': None, 'cuda': None})
        self.assertEqual(build_identity({'build_commit': None, 'build_backend': None, 'build_cuda': None}),
                         {'commit': None, 'backend': None, 'cuda': None})

    def test_the_identifier_names_the_artifact(self):
        meta = {"source": "local-cuda", "backend": "cuda", "version": "0.1.45",
                "commit": "46d239c9e1fecab7de9581d42bd2c0cefd0c8cca", "cuda": "12.9", "archs": [61]}
        got = build_identity({'build_commit': meta['commit'], 'build_backend': meta['backend'],
                              'build_cuda': meta['cuda']})
        self.assertEqual(got['backend'], 'cuda', 'the backend is the artifact backend')
        self.assertEqual(got['cuda'], '12.9', 'the CUDA version is the artifact CUDA version')
        self.assertTrue(got['commit'].startswith('46d239c9'), 'the commit is the artifact commit')
        self.assertLessEqual(len(got['commit']), 12, 'the commit is the short revision')
        # the app's rendering: commit, backend and CUDA, in that order
        parts = [got['commit'], got['backend'], f"CUDA {got['cuda']}" if got['cuda'] else None]
        self.assertEqual(" · ".join(p for p in parts if p), f"{got['commit']} · cuda · CUDA 12.9")

    def test_the_engine_version_is_still_reported(self):
        # the About card's "Engine" row is unchanged: the release identity is still there
        self.assertIn('eng.version ? `v${eng.version}`', APP_JS, 'the engine version row is unchanged')
        self.assertIn('"version"', SERVER, 'the server still reads the engine version')


if __name__ == '__main__':
    unittest.main()
