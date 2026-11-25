"""HX-50: optional macOS sandbox-exec around worker/escalate model calls."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import hx
from tests.helpers import fake_opencode, read_calls, temp_repo

STEP = json.dumps({"type": "step_finish", "timestamp": 1500, "sessionID": "s", "part": {"tokens": {"input": 1, "output": 1}}})
HAS_SANDBOX_EXEC = hx.sys.platform == "darwin" and shutil.which("sandbox-exec") is not None


class Base(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(hx.time, "sleep", lambda *_: None))
        self.repo = self.stack.enter_context(temp_repo())
        with contextlib.redirect_stdout(io.StringIO()):
            hx.cmd_new(NS(task="HX-S1", base=None, branch=None, setup=None))
        self.p = hx.task_paths("HX-S1")
        self.spec = Path(self.repo).parent / "spec.md"
        self.spec.write_text("# G\nx\n\n## Kapsam\nhx.py\n", encoding="utf-8")

    def run_captured(self, role, role_cfg=None, self_check=True, **kwargs):
        seen = {}

        def fake_streaming(args, cwd, env, limit, stall_limit):
            seen["args"], seen["env"] = args, env
            return STEP + "\n", "", False, False
        cfg = dict(hx.CFG["roles"][role], **(role_cfg or {}))
        patches = [mock.patch.dict(hx.CFG["roles"], {role: cfg}),
                   mock.patch.object(hx, "run_streaming", fake_streaming)]
        if self_check:
            patches.append(mock.patch.object(hx, "sandbox_self_check", lambda *_: None))
        with contextlib.ExitStack() as st:
            for p in patches:
                st.enter_context(p)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(seen.setdefault("stderr", io.StringIO())):
                result = hx.run_role(role, "HX-S1", str(self.spec), reap=False, **kwargs)
        seen["result"] = result
        return seen

    def call_records(self):
        text = (hx.state_dir() / "metrics.jsonl").read_text()
        return [json.loads(l) for l in text.splitlines() if json.loads(l).get("event") == "call"]


class NS:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class ProfileTest(Base):
    def test_profile_denies_the_real_hidden_and_state_dirs(self):
        profile = hx.sandbox_profile("worker", self.p["hidden"], hx.state_dir(), 3)
        self.assertEqual(hx.state_dir() / "sandbox-worker-3.sb", profile)
        a, b = os.path.realpath(str(self.p["hidden"])), os.path.realpath(str(hx.state_dir()))
        self.assertEqual(f'(version 1)\n(allow default)\n(deny file-read* file-write* (subpath "{a}") (subpath "{b}"))\n',
                         profile.read_text())

    def test_quote_or_backslash_in_a_path_is_rejected(self):
        for bad in ('/tmp/a"b', "/tmp/a\\b"):
            with self.assertRaises(SystemExit) as cm:
                hx.sandbox_profile("worker", bad, hx.state_dir(), 1)
            self.assertNotEqual(0, cm.exception.code)

    def test_non_sandbox_calls_have_no_profile_and_no_metric_field(self):
        seen = self.run_captured("worker")
        self.assertNotIn("sandbox-exec", seen["args"])
        self.assertNotIn("sandbox", self.call_records()[-1])
        self.assertEqual([], list(self.p["state"].glob("sandbox-*.sb")))


class AppliedTest(Base):
    def test_sandbox_wraps_opencode_adds_standalone_and_records_it(self):
        seen = self.run_captured("worker", {"sandbox": True})
        args = seen["args"]
        profile = self.p["state"] / "sandbox-worker-1.sb"
        self.assertEqual(["sandbox-exec", "-f", str(profile), "opencode", "run", "--standalone"], args[:6])
        self.assertTrue(profile.exists())
        self.assertIn(f'(subpath "{os.path.realpath(str(hx.state_dir()))}")', profile.read_text())
        self.assertTrue(self.call_records()[-1]["sandbox"])

    def test_two_calls_get_different_numbers(self):
        self.run_captured("worker")
        self.run_captured("worker")
        self.assertEqual([1, 2], [r["n"] for r in self.call_records()])

    def test_isolation_standalone_is_not_duplicated(self):
        seen = self.run_captured("worker", {"sandbox": True, "isolation": "worker"})
        self.assertEqual(1, seen["args"].count("--standalone"))

    def test_resume_session_arguments_survive(self):
        with mock.patch.object(hx, "last_session", lambda *_: "ses_old"):
            seen = self.run_captured("worker", {"sandbox": True}, resume=True)
        args = seen["args"]
        self.assertEqual("ses_old", args[args.index("--session") + 1])


class IgnoredTest(Base):
    def test_hidden_role_warns_and_is_not_sandboxed(self):
        seen = self.run_captured("tester", {"sandbox": True})
        self.assertEqual("hx: sandbox ignored for role tester\n", seen["stderr"].getvalue())
        self.assertNotIn("sandbox-exec", seen["args"])
        self.assertNotIn("sandbox", self.call_records()[-1])

    def test_read_only_role_warns_and_is_not_sandboxed(self):
        seen = self.run_captured("worker", {"sandbox": True}, read_only=True)
        self.assertEqual("hx: sandbox ignored for role worker\n", seen["stderr"].getvalue())
        self.assertNotIn("sandbox-exec", seen["args"])
        self.assertNotIn("sandbox", self.call_records()[-1])


class SelfCheckTest(Base):
    def check(self, runs):
        """sandbox_self_check with a faked subprocess.run; asserts the fail-closed SystemExit."""
        profile = hx.sandbox_profile("worker", self.p["hidden"], hx.state_dir(), 1)
        state = hx.state_dir()
        with mock.patch.object(hx.subprocess, "run", side_effect=runs):
            with self.assertRaises(SystemExit) as cm:
                hx.sandbox_self_check(profile, state)
        self.assertIn("sandbox self-check failed", str(cm.exception))

    def test_self_check_fails_when_the_canary_is_readable(self):
        readable = subprocess.CompletedProcess([], 0, "secret\n", "")
        true = subprocess.CompletedProcess([], 0, "", "")
        self.check([readable, true])

    def test_self_check_fails_when_cat_fails_without_operation_not_permitted(self):
        # cat exits non-zero but its stderr is e.g. ENOENT: the block was not proven.
        cat = subprocess.CompletedProcess([], 1, "", "/bin/cat: canary: No such file or directory")
        true = subprocess.CompletedProcess([], 0, "", "")
        self.check([cat, true])

    def test_self_check_fails_when_true_fails(self):
        cat = subprocess.CompletedProcess([], 1, "", "sandboxd: Operation not permitted")
        true = subprocess.CompletedProcess([], 1, "", "")
        self.check([cat, true])

    def test_self_check_fails_on_timeout(self):
        self.check([subprocess.TimeoutExpired(cmd=[], timeout=30)])

    def test_consecutive_self_checks_use_different_canary_names_and_leave_none_behind(self):
        calls = []

        def fake_run(args, **kw):
            calls.append(args)
            if args[3] == "/bin/cat":
                return subprocess.CompletedProcess(args, 1, "", "Operation not permitted")
            return subprocess.CompletedProcess(args, 0, "", "")

        profile = hx.sandbox_profile("worker", self.p["hidden"], hx.state_dir(), 1)
        state = hx.state_dir()
        with mock.patch.object(hx.subprocess, "run", side_effect=fake_run):
            hx.sandbox_self_check(profile, state)
            hx.sandbox_self_check(profile, state)
        cats = [c for c in calls if c[3] == "/bin/cat"]
        self.assertEqual(2, len(cats))
        self.assertNotEqual(cats[0][4], cats[1][4])
        self.assertTrue(Path(cats[0][4]).name.startswith(".sbx_canary-"))
        self.assertEqual([], list(hx.state_dir().glob(".sbx_canary*")))


class UnavailableTest(Base):
    def run_aborted(self, target, value):
        d = tempfile.mkdtemp(prefix="hx-fake-")
        self.addCleanup(shutil.rmtree, d, True)
        env = fake_opencode(d, [STEP])
        cfg = dict(hx.CFG["roles"]["worker"], sandbox=True)
        with contextlib.ExitStack() as st:
            st.enter_context(mock.patch.object(target[0], target[1], value))
            st.enter_context(mock.patch.dict(hx.CFG["roles"], {"worker": cfg}))
            st.enter_context(mock.patch.dict(os.environ, env))
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as cm:
                hx.run_role("worker", "HX-S1", str(self.spec), reap=False)
        return cm.exception, d

    def test_non_macos_fails_closed_before_the_model(self):
        exc, d = self.run_aborted((hx.sys, "platform"), "linux")
        self.assertNotEqual(0, exc.code)
        self.assertIn("sandbox unavailable", str(exc))
        self.assertEqual([], read_calls(d))

    def test_missing_sandbox_exec_fails_closed_before_the_model(self):
        exc, d = self.run_aborted((hx.shutil, "which"), lambda *_: None)
        self.assertNotEqual(0, exc.code)
        self.assertIn("sandbox unavailable", str(exc))
        self.assertEqual([], read_calls(d))

    def test_aborted_call_leaves_no_empty_role_jsonl(self):
        exc, _ = self.run_aborted((hx.sys, "platform"), "linux")
        self.assertNotEqual(0, exc.code)
        self.assertEqual([], list(self.p["state"].glob("worker-*.jsonl")))

    def test_retry_after_a_failed_sandbox_leaves_no_reservation(self):
        self.run_aborted((hx.sys, "platform"), "linux")
        seen = self.run_captured("worker")
        self.assertEqual(1, self.call_records()[-1]["n"])
        self.assertNotIn("sandbox-exec", seen["args"])


@unittest.skipUnless(HAS_SANDBOX_EXEC, "sandbox-exec is macOS-only")
class RealSandboxExecTest(Base):
    def test_self_check_passes_with_the_generated_profile(self):
        profile = hx.sandbox_profile("worker", self.p["hidden"], hx.state_dir(), 1)
        hx.sandbox_self_check(profile, hx.state_dir())
        self.assertEqual([], list(hx.state_dir().glob(".sbx_canary*")))

    def test_self_check_fails_closed_with_a_permissive_profile(self):
        profile = Path(hx.state_dir()) / "open.sb"
        profile.write_text("(version 1)\n(allow default)\n")
        with self.assertRaises(SystemExit) as cm:
            hx.sandbox_self_check(profile, hx.state_dir())
        self.assertIn("sandbox self-check failed", str(cm.exception))
        self.assertEqual([], list(hx.state_dir().glob(".sbx_canary*")))

    def test_failed_self_check_aborts_before_the_model(self):
        open_profile = Path(hx.state_dir()) / "open.sb"
        open_profile.write_text("(version 1)\n(allow default)\n")
        d = tempfile.mkdtemp(prefix="hx-fake-")
        self.addCleanup(shutil.rmtree, d, True)
        env = fake_opencode(d, [STEP])
        cfg = dict(hx.CFG["roles"]["worker"], sandbox=True)
        with mock.patch.object(hx, "sandbox_profile", lambda *_: open_profile), \
                mock.patch.dict(hx.CFG["roles"], {"worker": cfg}), mock.patch.dict(os.environ, env), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as cm:
            hx.run_role("worker", "HX-S1", str(self.spec), reap=False)
        self.assertIn("sandbox self-check failed", str(cm.exception))
        self.assertEqual([], read_calls(d))
        self.assertEqual([], list(self.p["state"].glob("worker-*.jsonl")))


if __name__ == "__main__":
    unittest.main()
