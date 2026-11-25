"""HX-49: `gaming_flags` (observe only), its gate reporting and the `hx scan-gaming` command."""
import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

import hx
from tests.helpers import temp_repo

PASS_CMD = 'python3 -c "pass"'


class NS:
    """Minimal argparse.Namespace stand-in for the cmd_* handlers."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True).stdout


def make_diff(path, added=(), removed=(), new=False, deleted=False, context=()):
    """One-file unified diff in the shape `git diff` prints."""
    head = [f"diff --git a/{path} b/{path}"]
    if new:
        head.append("new file mode 100644")
    if deleted:
        head.append("deleted file mode 100644")
    head.append(f"--- {'/dev/null' if new else 'a/' + path}")
    head.append(f"+++ {'/dev/null' if deleted else 'b/' + path}")
    head.append(f"@@ -1,{len(removed)} +1,{len(added)} @@")
    body = [f" {x}" for x in context] + [f"-{x}" for x in removed] + [f"+{x}" for x in added]
    return "\n".join(head + body) + "\n"


def kinds(flags, kind):
    return [f for f in flags if f["kind"] == kind]


class GamingFlagsTest(unittest.TestCase):
    def test_test_file_detection(self):
        for path in ("tests/a.py", "pkg/tests/deep/a.py", "test/a.py", "pkg/__tests__/a.js", "spec/a.rb",
                     "test_a.py", "src/a_test.py", "src/a.test.js", "src/a.spec.ts", "FooTests.cs", "FooTest.cs"):
            self.assertTrue(hx.is_test_file(path), path)
        for path in ("src/app.py", "README.md", "contest.py", "latest.py", "specs/a.py", "src/testing.py"):
            self.assertFalse(hx.is_test_file(path), path)

    def test_skip_markers_on_added_lines(self):
        for marker in ("@unittest.skip", "unittest.skip(", "pytest.mark.skip", "pytest.skip(",
                       "pytest.mark.xfail", ".skip(", ".only(", ".todo(", "skip: true", "{ skip",
                       "Skip =", "[Ignore"):
            flags = hx.gaming_flags(make_diff("tests/test_a.py", added=[f"x = {marker}"]))
            self.assertEqual(["skip"], [f["kind"] for f in flags], marker)

    def test_sleep_markers_on_added_lines(self):
        for marker in ("time.sleep(", "asyncio.sleep(", "setTimeout(", "Thread.Sleep(", "Task.Delay(",
                       "await sleep("):
            flags = hx.gaming_flags(make_diff("tests/test_a.py", added=[f"  {marker}1)"]))
            self.assertEqual(["sleep"], [f["kind"] for f in flags], marker)

    def test_retry_markers_are_case_insensitive(self):
        for marker in ("flaky", "RETRY", "Retries", "rerun"):
            flags = hx.gaming_flags(make_diff("tests/test_a.py", added=[f"# {marker} this"]))
            self.assertEqual(["retry"], [f["kind"] for f in flags], marker)

    def test_removed_lines_do_not_produce_line_flags(self):
        flags = hx.gaming_flags(make_diff("tests/test_a.py", removed=["time.sleep(1)", "pytest.skip"]))
        self.assertEqual([], flags)

    def test_non_test_files_are_ignored(self):
        flags = hx.gaming_flags(make_diff("src/app.py", added=["time.sleep(1)", "retry = True"],
                                          removed=["assert x", "assert y"]))
        self.assertEqual([], flags)

    def test_one_flag_per_matching_kind_on_the_same_line(self):
        flags = hx.gaming_flags(make_diff("tests/test_a.py", added=['retry_later(time.sleep(1)); x.skip(2)']))
        self.assertEqual(["skip", "sleep", "retry"], [f["kind"] for f in flags])

    def test_assert_removed_needs_more_removed_than_added(self):
        flags = hx.gaming_flags(make_diff("tests/test_a.py", removed=["assert a", "assert b"],
                                          added=["assert a"]))
        self.assertEqual([{"file": "tests/test_a.py", "kind": "assert_removed",
                           "line": "removed=2 added=1"}], flags)
        self.assertEqual([], hx.gaming_flags(make_diff("tests/test_a.py", removed=["assert a"],
                                                       added=["assert b"])))

    def test_assert_markers_are_case_sensitive(self):
        # "ASSERT" is not an assertion line; expect(, Assert. and .should are.
        flags = hx.gaming_flags(make_diff("spec/a_spec.rb", removed=["x.should eq(1)", "expect(y).to eq(2)"]))
        self.assertEqual(["assert_removed"], [f["kind"] for f in flags])
        self.assertEqual([], hx.gaming_flags(make_diff("tests/test_a.py", removed=["ASSERT a"])))

    def test_new_test_files_are_scanned(self):
        flags = hx.gaming_flags(make_diff("tests/test_new.py", added=["pytest.skip('x')"], new=True))
        self.assertEqual(["skip"], [f["kind"] for f in flags])

    def test_deleted_test_file(self):
        flags = hx.gaming_flags(make_diff("tests/test_gone.py", removed=["def test_x():", "    pass"],
                                          deleted=True))
        self.assertEqual([{"file": "tests/test_gone.py", "kind": "test_deleted", "line": ""}], flags)

    def test_deleted_test_file_does_not_report_assert_removed(self):
        flags = hx.gaming_flags(make_diff("tests/test_gone.py", removed=["assert a", "assert b"],
                                          deleted=True))
        self.assertEqual([{"file": "tests/test_gone.py", "kind": "test_deleted", "line": ""}], flags)

    def test_deleted_non_test_file_is_ignored(self):
        self.assertEqual([], hx.gaming_flags(make_diff("src/app.py", removed=["x = 1"], deleted=True)))

    def test_line_has_no_diff_prefix_and_is_cut_to_200_chars(self):
        long = "time.sleep(1) " + "x" * 300
        flags = hx.gaming_flags(make_diff("tests/test_a.py", added=[long]))
        self.assertEqual("time.sleep(1) " + "x" * 186, flags[0]["line"])
        self.assertEqual(200, len(flags[0]["line"]))

    def test_marker_past_the_cut_still_flags_and_the_line_is_cut(self):
        for kind, line in (("skip", "x" * 250 + " .skip("), ("sleep", "x" * 250 + " time.sleep(1)"),
                           ("retry", "x" * 250 + " flaky")):
            flags = hx.gaming_flags(make_diff("tests/test_a.py", added=[line]))
            self.assertEqual([kind], [f["kind"] for f in flags], kind)
            self.assertEqual(200, len(flags[0]["line"]))

    def test_headers_are_not_content(self):
        # A removed `--- foo` content line (rendered "---- foo") is content; the "--- a/..." header is not.
        diff = ("diff --git a/tests/test_a.py b/tests/test_a.py\n"
                "--- a/tests/test_a.py\n"
                "+++ b/tests/test_a.py\n"
                "@@ -1,2 +1,2 @@\n"
                "--- foo\n"
                "+assert x\n")
        flags = hx.gaming_flags(diff)
        self.assertEqual([], flags)

    def test_hunk_counters_keep_diff_like_content_inside_the_hunk(self):
        # Inside a hunk "-- x" is rendered "--- x" and "++ y" is rendered "+++ y"; both are content, not headings.
        diff = ("diff --git a/tests/test_a.py b/tests/test_a.py\n"
                "--- a/tests/test_a.py\n"
                "+++ b/tests/test_a.py\n"
                "@@ -1,1 +1,1 @@\n"
                "--- assert a\n"
                "+++ y\n")
        self.assertEqual([{"file": "tests/test_a.py", "kind": "assert_removed",
                           "line": "removed=1 added=0"}], hx.gaming_flags(diff))
        diff = ("diff --git a/tests/test_a.py b/tests/test_a.py\n"
                "--- a/tests/test_a.py\n"
                "+++ b/tests/test_a.py\n"
                "@@ -1,1 +1,1 @@\n"
                "--- x\n"
                "+++ time.sleep(1)\n")
        self.assertEqual([("sleep", "++ time.sleep(1)")],
                         [(f["kind"], f["line"]) for f in hx.gaming_flags(diff)])

    def test_lines_split_on_newline_only_and_cr_is_trimmed(self):
        # splitlines() would split one added line on form-feed/U+2028; split("\n") keeps it whole.
        for sep in ("\x0c", "\u2028"):
            diff = ("diff --git a/tests/test_a.py b/tests/test_a.py\n"
                    "--- a/tests/test_a.py\n"
                    "+++ b/tests/test_a.py\n"
                    "@@ -1,0 +1,1 @@\n"
                    f"+x = 1{sep}time.sleep(1)\n")
            flags = hx.gaming_flags(diff)
            self.assertEqual(["sleep"], [f["kind"] for f in flags], repr(sep))
            self.assertEqual(f"x = 1{sep}time.sleep(1)", flags[0]["line"])
        diff = "--- a/tests/test_a.py\r\n+++ b/tests/test_a.py\r\n+time.sleep(1)\r\n"
        self.assertEqual("time.sleep(1)", hx.gaming_flags(diff)[0]["line"])

    def test_multiple_files_keep_their_own_flags(self):
        diff = (make_diff("tests/test_a.py", added=["time.sleep(1)"])
                + make_diff("tests/test_b.py", added=["retry = 1"]))
        flags = hx.gaming_flags(diff)
        self.assertEqual(["tests/test_a.py", "tests/test_b.py"], [f["file"] for f in flags])
        self.assertEqual(["sleep", "retry"], [f["kind"] for f in flags])

    def test_hand_written_diff_without_hunk_header(self):
        diff = ("--- a/tests/test_a.py\n"
                "+++ b/tests/test_a.py\n"
                "+time.sleep(1)\n"
                "+retry = 1\n")
        self.assertEqual(["sleep", "retry"], [f["kind"] for f in hx.gaming_flags(diff)])

    def test_headerless_multiple_files_split_on_the_header_pair(self):
        diff = ("--- a/tests/test_a.py\n"
                "+++ b/tests/test_a.py\n"
                "+time.sleep(1)\n"
                "--- a/tests/test_b.py\n"
                "+++ b/tests/test_b.py\n"
                "+retry = 1\n")
        flags = hx.gaming_flags(diff)
        self.assertEqual([("tests/test_a.py", "sleep"), ("tests/test_b.py", "retry")],
                         [(f["file"], f["kind"]) for f in flags])

    def test_quoted_git_paths_are_unquoted(self):
        q = "\\303\\266"  # "ö" in git's C-quoted form
        diff = (f'diff --git "a/tests/t{q}.py" "b/tests/t{q}.py"\n'
                f'--- "a/tests/t{q}.py"\n'
                f'+++ "b/tests/t{q}.py"\n'
                "@@ -1 +1 @@\n"
                "+time.sleep(1)\n")
        self.assertEqual(["tests/tö.py"], [f["file"] for f in hx.gaming_flags(diff)])

    def test_diff_header_path_with_quote_and_non_ascii(self):
        # git quotes a path holding a quote; the non-ASCII byte may be raw UTF-8 or an octal escape.
        self.assertEqual('tö"x.py', hx._diff_header_path('+++ "a/tö\\"x.py"'))
        self.assertEqual('tö"x.py', hx._diff_header_path('+++ "a/t\\303\\266\\"x.py"'))

    def test_diff_header_path_decodes_all_c_escapes(self):
        self.assertEqual("a\x07b\x08c\x0cd\x0de\x0bf",
                         hx._diff_header_path('+++ "a\\ab\\bc\\fd\\re\\vf"'))

    def test_spaced_path_in_diff_git_line_is_split_by_symmetry(self):
        # git never quotes a space, so a spaced path only appears unquoted; an empty deleted file has
        # no ---/+++ heading and no hunk, the diff --git line is the only path source.
        diff = ("diff --git a/tests/x y b/tests/x y\n"
                "deleted file mode 100644\n")
        self.assertEqual([{"file": "tests/x y", "kind": "test_deleted", "line": ""}], hx.gaming_flags(diff))


def run_gate(**kwargs):
    args = dict(task="HX-G49", test=None, hidden_cmd=None, allow="**", protect=None,
                retry=0, gate_timeout=120, no_tests=False)
    args.update(kwargs)
    buf = io.StringIO()
    code = None
    with contextlib.redirect_stdout(buf):
        try:
            hx.cmd_gate(NS(**args))
        except SystemExit as e:
            code = e.code
    return code, buf.getvalue()


class GateGamingTest(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.repo = self.stack.enter_context(temp_repo())
        with contextlib.redirect_stdout(io.StringIO()):
            hx.cmd_new(NS(task="HX-G49", base=None, branch=None, setup=None))
        self.p = hx.task_paths("HX-G49")
        self.wt = self.p["worktree"]

    def tearDown(self):
        self.stack.close()

    def gate_metrics(self):
        lines = (hx.state_dir() / "metrics.jsonl").read_text().splitlines()
        return [r for r in (json.loads(l) for l in lines) if r.get("event") == "gate"]

    def test_flags_are_reported_but_do_not_change_the_verdict(self):
        (self.wt / "tests").mkdir()
        (self.wt / "tests" / "test_sleepy.py").write_text("import time\ntime.sleep(1)\n")
        code, out = run_gate(test=PASS_CMD)
        self.assertEqual(0, code)
        payload = json.loads(out.splitlines()[0])
        self.assertEqual("PASS", payload["gate"])
        self.assertEqual("observe", payload["gaming_mode"])
        self.assertEqual(["sleep"], [f["kind"] for f in payload["gaming_flags"]])
        self.assertIn("[hx] gate: 1 gaming flag(s) (observe only): sleep", out)
        saved = json.loads((self.p["state"] / "last_gate.txt").read_text())
        self.assertEqual("observe", saved["gaming_mode"])
        self.assertEqual(1, len(saved["gaming_flags"]))
        self.assertEqual(1, self.gate_metrics()[-1]["gaming_flags"])

    def test_no_flags_gives_an_empty_list_and_no_warning(self):
        (self.wt / "tests").mkdir()
        (self.wt / "tests" / "test_clean.py").write_text("x = 1\n")
        code, out = run_gate(test=PASS_CMD)
        self.assertEqual(0, code)
        payload = json.loads(out.splitlines()[0])
        self.assertEqual([], payload["gaming_flags"])
        self.assertNotIn("gaming flag(s)", out)
        self.assertEqual(0, self.gate_metrics()[-1]["gaming_flags"])

    def test_untracked_test_file_is_scanned_too(self):
        (self.wt / "tests").mkdir()
        (self.wt / "tests" / "test_new.py").write_text("pytest.skip('x')\n")
        code, out = run_gate(no_tests=True)
        self.assertEqual(0, code)
        payload = json.loads(out.splitlines()[0])
        self.assertEqual(["skip"], [f["kind"] for f in payload["gaming_flags"]])

    def test_quoted_non_ascii_path_is_reported_and_gate_json_is_writable(self):
        (self.wt / "tests").mkdir()
        name = 'tö"st.py'
        (self.wt / "tests" / name).write_text("time.sleep(1)\n")
        code, out = run_gate(test=PASS_CMD)
        self.assertEqual(0, code)
        payload = json.loads(out.splitlines()[0])
        self.assertEqual([f"tests/{name}"], [f["file"] for f in payload["gaming_flags"]])
        saved = json.loads((self.p["state"] / "last_gate.txt").read_text())
        self.assertEqual([f"tests/{name}"], [f["file"] for f in saved["gaming_flags"]])

    def test_gaming_scan_failure_does_not_change_the_verdict(self):
        (self.wt / "tests").mkdir()
        (self.wt / "tests" / "test_x.py").write_text("x = 1\n")
        for exc in (RuntimeError("boom"), SystemExit("boom")):
            with self.subTest(exc=type(exc).__name__), \
                    mock.patch.object(hx, "gaming_flags", side_effect=exc), \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                code, out = run_gate(test=PASS_CMD)
            self.assertEqual(0, code)
            payload = json.loads(out.splitlines()[0])
            self.assertEqual("PASS", payload["gate"])
            self.assertEqual([], payload["gaming_flags"])
            self.assertEqual("observe", payload["gaming_mode"])
            self.assertIn("boom", payload["gaming_error"])
            self.assertIn("gaming scan failed", err.getvalue())


class ScanGamingCliTest(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.repo = self.stack.enter_context(temp_repo())
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_a.py").write_text("def test_x():\n    assert 1 == 1\n")
        git(self.repo, "add", "tests/test_a.py")
        git(self.repo, "commit", "-q", "-m", "base")
        (self.repo / "tests" / "test_a.py").write_text(
            "def test_x():\n    assert 1 == 1\n    time.sleep(1)\n    retry = 1\n")
        git(self.repo, "add", "tests/test_a.py")
        git(self.repo, "commit", "-q", "-m", "change")

    def tearDown(self):
        self.stack.close()

    def run_cli(self, *argv):
        buf = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(buf), mock.patch.object(sys, "argv", ["hx", *argv]):
            try:
                hx.main()
            except SystemExit as e:
                code = e.code
        return code, buf.getvalue()

    def test_tab_lines_and_summary(self):
        code, out = self.run_cli("scan-gaming", str(self.repo), "HEAD~1", "HEAD")
        self.assertEqual(0, code)
        lines = out.splitlines()
        self.assertEqual("sleep\ttests/test_a.py\t    time.sleep(1)", lines[0])
        self.assertEqual("retry\ttests/test_a.py\t    retry = 1", lines[1])
        self.assertEqual("flags=2", lines[-1])

    def test_json_output(self):
        code, out = self.run_cli("scan-gaming", str(self.repo), "HEAD~1", "HEAD", "--json")
        self.assertEqual(0, code)
        lines = out.splitlines()
        flags = json.loads(lines[0])
        self.assertEqual(["sleep", "retry"], [f["kind"] for f in flags])
        self.assertEqual("flags=2", lines[-1])

    def test_bad_revision_exits_non_zero(self):
        code, _ = self.run_cli("scan-gaming", str(self.repo), "no-such-rev", "HEAD")
        self.assertNotEqual(0, code)

    def test_bad_repo_exits_non_zero(self):
        code, _ = self.run_cli("scan-gaming", os.path.join(str(self.repo), "missing"), "HEAD~1", "HEAD")
        self.assertNotEqual(0, code)

    def test_option_like_revision_exits_non_zero(self):
        code, _ = self.run_cli("scan-gaming", str(self.repo), "--", "-x", "HEAD")
        self.assertNotEqual(0, code)

    def test_non_ascii_path_is_reported_raw(self):
        p = self.repo / "tests" / "tö.py"
        p.write_text("x = 1\n")
        git(self.repo, "add", "tests/tö.py")
        git(self.repo, "commit", "-q", "-m", "non-ascii")
        p.write_text("x = 1\nretry = 1\n")
        git(self.repo, "add", "tests/tö.py")
        git(self.repo, "commit", "-q", "-m", "non-ascii change")
        code, out = self.run_cli("scan-gaming", str(self.repo), "HEAD~1", "HEAD")
        self.assertEqual(0, code)
        self.assertEqual("retry\ttests/tö.py\tretry = 1", out.splitlines()[0])
        self.assertEqual("flags=1", out.splitlines()[-1])

    def test_deleted_empty_test_file(self):
        # an empty deleted file has no ---/+++ heading and no hunk; the path must come from the diff --git line
        (self.repo / "tests" / "test_empty.py").write_text("")
        git(self.repo, "add", "tests/test_empty.py")
        git(self.repo, "commit", "-q", "-m", "empty test file")
        git(self.repo, "rm", "-q", "tests/test_empty.py")
        git(self.repo, "commit", "-q", "-m", "delete empty test file")
        code, out = self.run_cli("scan-gaming", str(self.repo), "HEAD~1", "HEAD", "--json")
        self.assertEqual(0, code)
        flags = json.loads(out.splitlines()[0])
        self.assertEqual([("tests/test_empty.py", "test_deleted")], [(f["file"], f["kind"]) for f in flags])

    def test_user_diff_config_does_not_break_the_file_name(self):
        # diff.noprefix/mnemonicPrefix and diff.external/textconv must not change the header shapes:
        # the diff is taken with pinned a/ b/ prefixes, no textconv, no external driver.
        for key, value in (("diff.noprefix", "true"), ("diff.mnemonicPrefix", "true"),
                           ("diff.external", "false")):
            git(self.repo, "config", key, value)
        (self.repo / "tests" / "test_prefix.py").write_text("time.sleep(1)\n")
        git(self.repo, "add", "tests/test_prefix.py")
        git(self.repo, "commit", "-q", "-m", "noprefix change")
        code, out = self.run_cli("scan-gaming", str(self.repo), "HEAD~1", "HEAD")
        self.assertEqual(0, code)
        self.assertEqual("sleep\ttests/test_prefix.py\ttime.sleep(1)", out.splitlines()[0])

    def test_gaming_diff_pins_prefixes_under_user_config(self):
        git(self.repo, "config", "diff.noprefix", "true")
        (self.repo / "tests" / "test_prefix.py").write_text("time.sleep(1)\n")
        flags = hx.gaming_flags(hx.gaming_diff(self.repo, "HEAD"))
        self.assertEqual(["sleep"], [f["kind"] for f in flags])
        self.assertEqual("tests/test_prefix.py", flags[0]["file"])

    def test_zero_flags_non_json_prints_only_the_summary(self):
        code, out = self.run_cli("scan-gaming", str(self.repo), "HEAD", "HEAD")
        self.assertEqual(0, code)
        self.assertEqual(["flags=0"], out.splitlines())

    def test_invalid_utf8_diff_is_decoded_and_printed_safely(self):
        (self.repo / "tests" / "test_bin.py").write_bytes(b"time.sleep(1) \xff\n")
        git(self.repo, "add", "tests/test_bin.py")
        git(self.repo, "commit", "-q", "-m", "invalid utf-8")
        code, out = self.run_cli("scan-gaming", str(self.repo), "HEAD~1", "HEAD")
        self.assertEqual(0, code)
        self.assertEqual(1, len([l for l in out.splitlines() if l.startswith("sleep\ttests/test_bin.py\t")]))
        self.assertEqual("flags=1", out.splitlines()[-1])


if __name__ == "__main__":
    unittest.main()
