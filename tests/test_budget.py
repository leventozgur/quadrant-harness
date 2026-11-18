"""Worker/escalate retry budget (HX-28) and triage BELIRSIZ handling.

The fake `opencode` never talks to the network; sleeps are patched out so no test waits.
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import hx
from tests.helpers import fake_opencode, read_calls, temp_repo

SPEC_TEXT = """# Görev
metin

## Gizli test biçimi
gizli ayrıntı: tests/gizli_test.py

## Kapsam
hx.py
"""

JUDGE_TEXT = ("KOD_HATASI — kural bir — kod yanlış\n"
              "TEST_HATASI — test_foo — spec dışı\n"
              "BELIRSIZ — test_bar — neden belli değil\n"
              "BELIRSIZ – test_baz – ikinci neden\n"
              "BELIRSIZ - test_qux - üçüncü neden\n"
              "BELIRSIZ yok.\n"
              "BELIRSIZ —   \n")


class NS:
    """Minimal argparse.Namespace stand-in for the cmd_* handlers."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def event_stream(text="bitti"):
    return [
        json.dumps({"type": "step_start", "timestamp": 1000, "sessionID": "ses_x",
                    "part": {"messageID": "m1"}}),
        json.dumps({"type": "text", "timestamp": 1200, "sessionID": "ses_x",
                    "part": {"messageID": "m1", "text": text}}),
        json.dumps({"type": "step_finish", "timestamp": 1500, "sessionID": "ses_x",
                    "part": {"tokens": {"input": 10, "output": 5}}}),
    ]


class Base(unittest.TestCase):
    task = "HX-B1"

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.dict(hx.CFG, {"rate_limit_wait_s": 0}))
        self.stack.enter_context(mock.patch.object(hx.time, "sleep", lambda *_: None))
        self.stack.enter_context(mock.patch.object(hx, "reap_orphans", lambda *_, **__: 0))
        self.repo = self.stack.enter_context(temp_repo())
        with contextlib.redirect_stdout(io.StringIO()):
            hx.cmd_new(NS(task=self.task, base=None, branch=None, setup=None))
        self.p = hx.task_paths(self.task)
        self.spec = Path(self.repo).parent / "spec.md"
        self.spec.write_text(SPEC_TEXT, encoding="utf-8")
        self.fake_dir = tempfile.mkdtemp(prefix="hx-fake-")
        self.addCleanup(shutil.rmtree, self.fake_dir, True)
        env = fake_opencode(self.fake_dir, event_stream())
        self.stack.enter_context(mock.patch.dict(os.environ, env))

    # ---------------------------------------------------------------- helpers
    def call(self, role="worker", **kwargs):
        args = dict(task=self.task, role=role, spec=str(self.spec), feedback=None, model=None,
                    read_only=False, max_chars=2500, timeout=None, resume=False, force_retry=False)
        args.update(kwargs)
        buf = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(buf):
            try:
                hx.cmd_call(NS(**args))
            except SystemExit as e:
                code = e.code
        return code, buf.getvalue()

    def pair(self):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                hx.cmd_pair(NS(task=self.task, spec=str(self.spec), max_chars=2500))
            except SystemExit as e:
                code = e.code
        return code

    def calls(self):
        path = self.p["state"].parent / "metrics.jsonl"
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def role_calls(self, role="worker"):
        return [r for r in self.calls() if r.get("event") == "call" and r.get("role") == role]

    def judge(self, text):
        fake_opencode(self.fake_dir, [json.dumps({"type": "text", "timestamp": 1000, "sessionID": "ses_j",
                                                  "part": {"messageID": "m1", "text": text}})])
        (self.p["state"] / "hidden_failure.txt").write_text("1 hidden test failed\n", encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            hx.cmd_triage(NS(task=self.task, spec=str(self.spec), max_chars=2500))
        return buf.getvalue()


class WorkerBudgetTest(Base):
    def test_worker_first_call_plus_two_retries_then_refused(self):
        for i in (1, 2, 3):
            self.assertEqual(0, self.call()[0], i)
        self.assertEqual(3, len(read_calls(self.fake_dir)))
        code, _ = self.call()
        self.assertNotEqual(0, code)
        self.assertIn("escalate", str(code))
        self.assertEqual(3, len(read_calls(self.fake_dir)))
        self.assertFalse((self.p["state"] / "worker-4.jsonl").exists())
        self.assertEqual(3, len(self.role_calls("worker")))

    def test_resumed_call_is_not_counted_and_never_refused(self):
        for _ in range(3):
            self.call()
        self.assertEqual(0, self.call(resume=True)[0])
        recs = self.role_calls("worker")
        self.assertEqual(4, len(recs))
        self.assertTrue(recs[-1]["resumed"])
        self.assertEqual(3, len([r for r in recs if not r["resumed"]]))
        self.assertIn("escalate", str(self.call()[0]))
        self.assertEqual(4, len(read_calls(self.fake_dir)))

    def test_phase_commit_resets_the_window(self):
        for _ in range(3):
            self.call()
        self.assertIn("escalate", str(self.call()[0]))
        hx.metric({"task": self.task, "event": "phase_commit", "phase": "1", "commit": "x"})
        self.assertEqual(0, self.call()[0])

    def test_escalate_is_allowed_once_per_phase(self):
        self.assertEqual(0, self.call(role="escalate")[0])
        code, _ = self.call(role="escalate")
        self.assertIn("escalate", str(code))
        self.assertFalse((self.p["state"] / "escalate-2.jsonl").exists())
        self.assertEqual(1, len(read_calls(self.fake_dir)))

    def test_force_retry_overrides_the_limit_and_is_recorded(self):
        for _ in range(3):
            self.call()
        self.assertIn("escalate", str(self.call()[0]))
        self.assertEqual(0, self.call(force_retry=True)[0])
        recs = self.role_calls("worker")
        self.assertEqual(4, len(recs))
        self.assertTrue(recs[-1]["forced"])
        self.assertNotIn("forced", recs[0])

    def test_missing_config_key_means_two_retries(self):
        with mock.patch.dict(hx.CFG, {}, clear=False):
            hx.CFG.pop("max_worker_retries", None)
            self.assertEqual(2, hx.max_worker_retries())
            for _ in range(3):
                self.assertEqual(0, self.call()[0])
            self.assertIn("escalate", str(self.call()[0]))

    def test_tester_calls_are_not_limited(self):
        for _ in range(5):
            self.assertEqual(0, self.call(role="tester")[0])

    def test_pair_worker_call_counts_toward_the_budget(self):
        self.assertEqual(0, self.pair())
        self.assertEqual(1, len([r for r in self.role_calls("worker") if not r["resumed"]]))
        self.assertEqual(0, self.call()[0])
        self.assertEqual(0, self.call()[0])
        self.assertIn("escalate", str(self.call()[0]))
        self.assertEqual(3, len([r for r in self.role_calls("worker") if not r["resumed"]]))

    def test_pair_is_never_blocked_by_the_budget(self):
        for _ in range(3):
            self.assertEqual(0, self.call()[0])
        self.assertEqual(0, self.pair())
        self.assertEqual(4, len(self.role_calls("worker")))

    def test_cli_force_retry_flag_reaches_the_call_command(self):
        seen = {}

        def fake_cmd_call(args):
            seen.update(vars(args))

        argv = ["hx", "call", "worker", self.task, str(self.spec), "--force-retry"]
        with mock.patch.object(hx, "cmd_call", fake_cmd_call), mock.patch.object(sys, "argv", argv):
            hx.main()
        self.assertTrue(seen["force_retry"])
        self.assertEqual("worker", seen["role"])


class TriageUnclearTest(Base):
    def test_unclear_lines_go_to_test_issues_under_their_own_heading(self):
        out = self.judge(JUDGE_TEXT)
        issues = (self.p["state"] / "test_issues.txt").read_text(encoding="utf-8")
        fb = (self.p["state"] / "worker_feedback.txt").read_text(encoding="utf-8")
        lines = issues.splitlines()
        self.assertEqual("TEST_HATASI — test_foo — spec dışı", lines[0])
        self.assertEqual("BELIRSIZ:", lines[1])
        self.assertEqual(["BELIRSIZ — test_bar — neden belli değil",
                          "BELIRSIZ – test_baz – ikinci neden",
                          "BELIRSIZ - test_qux - üçüncü neden"], lines[2:])
        self.assertNotIn("BELIRSIZ", fb)
        self.assertNotIn("test_bar", fb)
        self.assertNotIn("test_bar", issues.split("BELIRSIZ:")[0])
        triage = [r for r in self.calls() if r.get("event") == "triage"][-1]
        self.assertEqual(1, triage["test_errors"])
        self.assertEqual(3, triage["unclear"])
        self.assertIn("unclear=3", out)

    def test_no_unclear_lines_means_no_heading(self):
        self.judge("KOD_HATASI — kural bir — kod yanlış\nTEST_HATASI — test_foo — spec dışı\n")
        issues = (self.p["state"] / "test_issues.txt").read_text(encoding="utf-8")
        self.assertNotIn("BELIRSIZ", issues)
        triage = [r for r in self.calls() if r.get("event") == "triage"][-1]
        self.assertEqual(0, triage["unclear"])

    def test_unclear_only_still_gets_its_heading(self):
        out = self.judge("BELIRSIZ — test_bar — neden belli değil\n")
        issues = (self.p["state"] / "test_issues.txt").read_text(encoding="utf-8")
        self.assertEqual(["BELIRSIZ:", "BELIRSIZ — test_bar — neden belli değil"], issues.splitlines())
        self.assertIn("test_errors=0", out)
        self.assertIn("unclear=1", out)


class ReportUnclearTest(Base):
    def test_report_shows_unclear_and_treats_old_records_as_zero(self):
        hx.metric({"task": self.task, "event": "triage", "code_errors": 1, "test_errors": 1})
        hx.metric({"task": self.task, "event": "triage", "code_errors": 1, "test_errors": 1, "unclear": 2})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            hx.cmd_report(NS())
        self.assertIn("triage(code/test/unclear)=2/2/2", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
