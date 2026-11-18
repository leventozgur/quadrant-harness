"""HX-25: hardened `hx gate` — mandatory test command / allow-list, `**` globs, spaced paths, timeout."""
import contextlib
import io
import json
import subprocess
import unittest

import hx
from tests.helpers import temp_repo

PASS_CMD = 'python3 -c "pass"'


class NS:
    """Minimal argparse.Namespace stand-in for cmd_gate."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def run_gate(**kwargs):
    """Call cmd_gate with defaults; returns (SystemExit code, first JSON payload or None, stdout)."""
    args = dict(task="HX-G1", test=None, hidden_cmd=None, allow="**", protect=None,
                retry=0, gate_timeout=120, no_tests=False)
    args.update(kwargs)
    buf = io.StringIO()
    code = None
    with contextlib.redirect_stdout(buf):
        try:
            hx.cmd_gate(NS(**args))
        except SystemExit as e:
            code = e.code
    payload = None
    for line in buf.getvalue().splitlines():
        if line.startswith("{"):
            payload = json.loads(line)
            break
    return code, payload, buf.getvalue()


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True).stdout


class GateTest(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.repo = self.stack.enter_context(temp_repo())
        with contextlib.redirect_stdout(io.StringIO()):
            hx.cmd_new(NS(task="HX-G1", base=None, branch=None, setup=None))
        self.p = hx.task_paths("HX-G1")
        self.wt = self.p["worktree"]

    def tearDown(self):
        self.stack.close()

    # ---------------------------------------------------------------- mandatory inputs
    def test_gate_requires_a_test_command(self):
        code, payload, _ = run_gate(test=None, hidden_cmd=None)
        self.assertNotEqual(0, code)
        self.assertIn("--test", str(code))
        self.assertIn("--no-tests", str(code))
        self.assertIsNone(payload)
        self.assertFalse((self.p["state"] / "last_gate.json").exists())
        self.assertFalse((self.p["state"] / "tests.log").exists())
        self.assertFalse((self.p["state"] / "visible_failure.txt").exists())

    def test_no_tests_flag_gates_without_a_test_command(self):
        (self.wt / "impl.py").write_text("x = 1\n")
        code, payload, _ = run_gate(no_tests=True)
        self.assertEqual(0, code)
        self.assertIs(True, payload["no_tests"])
        self.assertNotIn("tests", payload)
        self.assertEqual("PASS", payload["gate"])
        saved = json.loads((self.p["state"] / "last_gate.json").read_text())
        self.assertEqual("PASS", saved["gate"])
        self.assertIs(True, saved["no_tests"])
        self.assertIs(True, json.loads((self.p["state"] / "last_gate.txt").read_text())["no_tests"])

    def test_no_tests_flag_skips_a_given_test_command(self):
        code, payload, _ = run_gate(no_tests=True, test="exit 3")
        self.assertEqual(0, code)
        self.assertIs(True, payload["no_tests"])
        self.assertNotIn("tests", payload)

    def test_gate_requires_an_allow_list(self):
        for allow in (None, "", " , "):
            code, payload, _ = run_gate(test=PASS_CMD, allow=allow)
            self.assertNotEqual(0, code)
            self.assertIn("--allow", str(code))
            self.assertIsNone(payload)
            self.assertFalse((self.p["state"] / "last_gate.json").exists())

    # ---------------------------------------------------------------- glob semantics
    def test_glob_semantics(self):
        cases = [
            # ** = zero or more whole directory segments
            ("a/b.py", "a/**/b.py", True),
            ("a/x/y/b.py", "a/**/b.py", True),
            ("a/xb.py", "a/**/b.py", False),
            ("src/x.py", "src/**", True),
            ("src/a/b.py", "src/**", True),
            ("src", "src/**", False),
            ("other/x.py", "src/**", False),
            ("anything/at/all.txt", "**", True),
            ("test_a.py", "**/test_*.py", True),
            ("deep/x/test_a.py", "**/test_*.py", True),
            # * and ? never cross "/"
            ("tests/a.py", "tests/*", True),
            ("tests/sub/a.py", "tests/*", False),
            ("tests/sub/a.py", "tests/**", True),
            ("README.md", "*.md", True),
            ("docs/a.md", "*.md", False),
            ("src/a.py", "*.py", False),
            ("axb", "a?b", True),
            ("a/b", "a?b", False),
            # character classes: one character, "/" excluded
            ("a1.py", "a[12].py", True),
            ("a3.py", "a[12].py", False),
            ("a/.py", "a[!x].py", False),
            ("a^.py", "a[^x].py", True),
            ("ax.py", "a[^x].py", True),
            ("ab.py", "a[^x].py", False),
            ("a\\.py", "a[^x].py", False),
            # whole-path match, not a prefix match
            ("a/b/c", "a/*/c", True),
            ("a/b/d/c", "a/*/c", False),
            ("docs/README.md", "README.md", False),
        ]
        for path, pattern, expected in cases:
            self.assertEqual(expected, hx.glob_match(path, pattern), f"{path} vs {pattern}")

    def test_star_star_allow_covers_nested_paths(self):
        (self.wt / "pkg" / "deep").mkdir(parents=True)
        (self.wt / "pkg" / "deep" / "a.py").write_text("x\n")
        code, payload, _ = run_gate(test=PASS_CMD, allow="**")
        self.assertEqual(0, code)
        self.assertEqual(["pkg/deep/a.py"], payload["changed"])
        self.assertEqual([], payload["out_of_scope"])

    def test_single_star_allow_does_not_cover_subdirectories(self):
        (self.wt / "tests" / "sub").mkdir(parents=True)
        (self.wt / "tests" / "a.py").write_text("a\n")
        (self.wt / "tests" / "sub" / "b.py").write_text("b\n")
        code, payload, _ = run_gate(test=PASS_CMD, allow="tests/*")
        self.assertEqual(1, code)
        self.assertEqual(["tests/sub/b.py"], payload["out_of_scope"])

    def test_protect_uses_the_same_glob_semantics(self):
        (self.wt / "secret" / "deep").mkdir(parents=True)
        (self.wt / "secret" / "deep" / "k.txt").write_text("k\n")
        code, payload, _ = run_gate(test=PASS_CMD, allow="**", protect="secret/**")
        self.assertEqual(1, code)
        self.assertEqual(["secret/deep/k.txt"], payload["protected_touched"])

    # ---------------------------------------------------------------- spaced paths
    def test_changed_files_keeps_spaces_for_untracked_files(self):
        (self.wt / "my dir").mkdir()
        (self.wt / "my dir" / "a b.py").write_text("x\n")
        self.assertEqual(["my dir/a b.py"], hx.changed_files(self.wt, self.p["base"]))

    def test_changed_files_keeps_spaces_for_tracked_files(self):
        (self.wt / "a b.py").write_text("v1\n")
        git(self.wt, "add", "a b.py")
        git(self.wt, "commit", "-q", "-m", "add spaced file")
        (self.wt / "a b.py").write_text("v2\n")
        self.assertEqual(["a b.py"], hx.changed_files(self.wt, self.p["base"]))

    def test_gate_scope_accepts_spaced_paths(self):
        (self.wt / "my dir").mkdir()
        (self.wt / "my dir" / "a b.py").write_text("x\n")
        code, payload, _ = run_gate(test=PASS_CMD, allow="my dir/**")
        self.assertEqual(0, code)
        self.assertEqual(["my dir/a b.py"], payload["changed"])
        self.assertEqual([], payload["out_of_scope"])

    # ---------------------------------------------------------------- timeout
    def test_visible_timeout_fails_without_retry(self):
        (self.wt / "attempts.txt").write_text("")
        cmd = "echo x >> attempts.txt && echo started && sleep 5"
        code, payload, _ = run_gate(test=cmd, gate_timeout=1, retry=2)
        self.assertEqual(1, code)
        self.assertEqual("timeout", payload["tests"])
        self.assertEqual("FAIL", payload["gate"])
        self.assertNotIn("tests_retried", payload)
        self.assertEqual(1, len((self.wt / "attempts.txt").read_text().splitlines()))
        self.assertIn("started", (self.p["state"] / "tests.log").read_text())
        text = (self.p["state"] / "visible_failure.txt").read_text()
        self.assertIn("TIMEOUT", text)
        self.assertIn("limit 1s", text)
        self.assertRegex(text, r"TIMEOUT after \d+\.\ds")
        self.assertFalse((self.p["state"] / "hidden_failure.txt").exists())
        self.assertEqual("FAIL", json.loads((self.p["state"] / "last_gate.json").read_text())["gate"])

    def test_hidden_timeout_fails_gate_and_writes_hidden_failure(self):
        code, payload, _ = run_gate(test=None, hidden_cmd="echo hidden-start && sleep 5", gate_timeout=1)
        self.assertEqual(1, code)
        self.assertEqual("timeout", payload["hidden"])
        self.assertNotIn("tests", payload)
        text = (self.p["state"] / "hidden_failure.txt").read_text()
        self.assertIn("TIMEOUT", text)
        self.assertIn("hidden-start", text)
        self.assertFalse((self.p["state"] / "visible_failure.txt").exists())

    def test_timeout_log_is_empty_when_the_command_printed_nothing(self):
        code, payload, _ = run_gate(test="sleep 5", gate_timeout=1)
        self.assertEqual(1, code)
        self.assertEqual("", (self.p["state"] / "tests.log").read_text())
        self.assertIn("TIMEOUT", (self.p["state"] / "visible_failure.txt").read_text())


if __name__ == "__main__":
    unittest.main()
