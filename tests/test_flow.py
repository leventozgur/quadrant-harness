"""End-to-end flows against a throwaway git repo and a fake `opencode` on PATH."""
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

PASS_CMD = 'python3 -c "pass"'
FAIL_CMD = "echo boom && exit 3"

SPEC_TEXT = """# Görev
metin

## Gizli test biçimi
gizli ayrıntı: tests/gizli_test.py

## Kapsam
hx.py
"""

JUDGE_TEXT = ("KOD_HATASI — birinci kural — kod yanlış\n"
              "TEST_HATASI — test_foo — spec dışı\n"
              "KOD_HATASI yok.")


class NS:
    """Minimal argparse.Namespace stand-in for the cmd_* handlers."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True).stdout


def event_stream(final_text, timestamp=1000):
    """One opencode JSON event stream: text, one tool call and one step_finish with tokens."""
    return [
        json.dumps({"type": "step_start", "timestamp": timestamp, "sessionID": "ses_x",
                    "part": {"messageID": "m1"}}),
        json.dumps({"type": "text", "timestamp": timestamp + 500, "sessionID": "ses_x",
                    "part": {"messageID": "m1", "text": final_text}}),
        json.dumps({"type": "tool_use", "timestamp": timestamp + 600, "sessionID": "ses_x",
                    "part": {"tool": "shell", "state": {"input": {"command": "ls"}}}}),
        json.dumps({"type": "step_finish", "timestamp": timestamp + 1000, "sessionID": "ses_x",
                    "part": {"tokens": {"input": 100, "output": 20, "reasoning": 5,
                                        "cache": {"read": 50, "write": 0}}}}),
    ]


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        # run_streaming polls every 2 s; the fake opencode exits instantly, so skip that idle wait in tests
        self.stack.enter_context(mock.patch.object(hx.time, "sleep", lambda *_: None))

    # ---------------------------------------------------------------- helpers
    def new_task(self, task="HX-T1"):
        repo = self.stack.enter_context(temp_repo())
        with contextlib.redirect_stdout(io.StringIO()):
            hx.cmd_new(NS(task=task, base=None, branch=None, setup=None))
        return repo, hx.task_paths(task)

    def write_spec(self, repo, text=SPEC_TEXT):
        spec = Path(repo).parent / "spec.md"
        spec.write_text(text, encoding="utf-8")
        return spec

    def make_fake(self, lines, **kwargs):
        directory = tempfile.mkdtemp(prefix="hx-fake-")
        self.addCleanup(shutil.rmtree, directory, True)
        return directory, fake_opencode(directory, lines, **kwargs)

    def gate(self, **kwargs):
        args = dict(task="HX-T1", test=PASS_CMD, hidden_cmd=None, allow="**", protect=None,
                    retry=0, gate_timeout=120, no_tests=False)
        args.update(kwargs)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                hx.cmd_gate(NS(**args))
        payload = None
        for line in buf.getvalue().splitlines():
            if line.startswith("{"):
                payload = json.loads(line)
                break
        self.assertIsNotNone(payload, buf.getvalue())
        return cm.exception.code, payload

    def commit(self, **kwargs):
        args = dict(task="HX-T1", m="phase one", review="ONAY", phase="1", next=None)
        args.update(kwargs)
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                hx.cmd_commit(NS(**args))
        return cm.exception.code

    def record_review(self, text="ONAY\n", task="HX-T1"):
        """hx diff, then hx review with `text` as the reviewer output. Returns the exit code of cmd_review."""
        p = hx.task_paths(task)
        with contextlib.redirect_stdout(io.StringIO()):
            hx.cmd_diff(NS(task=task, all=False))
        out = p["state"] / "reviewer_output.md"
        out.write_text(text, encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                hx.cmd_review(NS(task=task, output=str(out)))
        return cm.exception.code

    # ---------------------------------------------------------------- HX-29 review record
    def test_review_records_onay_with_the_diff_hash(self):
        _, p = self.new_task()
        (p["worktree"] / "impl.py").write_text("v1\n")
        self.assertEqual(0, self.record_review("ONAY\n"))
        rec = json.loads((p["state"] / "review.json").read_text())
        self.assertEqual("ONAY", rec["verdict"])
        self.assertEqual(hx.diff_sha((p["state"] / "review.diff").read_text()), rec["diff_sha256"])

    def test_review_findings_are_red_and_commit_refuses(self):
        _, p = self.new_task()
        (p["worktree"] / "impl.py").write_text("v1\n")
        self.gate()
        self.assertEqual(1, self.record_review("impl.py:1 — sorun — düzelt\n"))
        self.assertEqual("RED", json.loads((p["state"] / "review.json").read_text())["verdict"])
        self.assertIn("not ONAY", str(self.commit(review=None)))

    def test_onay_followed_by_findings_is_red(self):
        self.assertEqual(("RED", ["impl.py:1 — sorun"]), hx.parse_review_verdict("ONAY\nimpl.py:1 — sorun\n"))
        self.assertEqual(("ONAY", []), hx.parse_review_verdict("\n**ONAY**\n"))
        self.assertEqual(("RED", []), hx.parse_review_verdict("RED\n"))
        # markdown bold, trailing space/period/newlines and lowercase are all the single-line ONAY
        for text in ("**ONAY**", "ONAY ", "ONAY\n\n", " onay.", "`ONAY`", "> ONAY\n", "# ONAY"):
            self.assertEqual(("ONAY", []), hx.parse_review_verdict(text), repr(text))
        for text in ("ONAY\n\nbir bulgu", "ONAYLANDI", "ONAY değil", "", "\n  \n"):
            self.assertEqual("RED", hx.parse_review_verdict(text)[0], repr(text))

    def test_commit_refuses_without_a_recorded_review(self):
        _, p = self.new_task()
        (p["worktree"] / "impl.py").write_text("v1\n")
        self.gate()
        self.assertIn("no recorded review", str(self.commit(review="ONAY")))

    def test_commit_refuses_an_onay_given_for_an_older_diff(self):
        _, p = self.new_task()
        wt = p["worktree"]
        (wt / "impl.py").write_text("v1\n")
        self.assertEqual(0, self.record_review())
        (wt / "impl.py").write_text("v2\n")  # tree changes after the ONAY, then gets gated again
        self.gate()
        self.assertIn("older diff", str(self.commit(review="ONAY")))

    def test_review_needs_a_diff_and_a_reviewer_output(self):
        _, p = self.new_task()
        with self.assertRaises(SystemExit) as cm:
            hx.cmd_review(NS(task="HX-T1", output=str(p["state"] / "none.md")))
        self.assertIn("hx diff", str(cm.exception.code))
        (p["worktree"] / "impl.py").write_text("v1\n")
        with contextlib.redirect_stdout(io.StringIO()):
            hx.cmd_diff(NS(task="HX-T1", all=False))
        with self.assertRaises(SystemExit) as cm:
            hx.cmd_review(NS(task="HX-T1", output=str(p["state"] / "none.md")))
        self.assertIn("not found", str(cm.exception.code))

    def test_review_record_is_consumed_by_the_commit(self):
        _, p = self.new_task()
        (p["worktree"] / "impl.py").write_text("v1\n")
        self.gate()
        self.assertEqual(0, self.record_review())
        with contextlib.redirect_stdout(io.StringIO()):
            hx.cmd_commit(NS(task="HX-T1", m="p", review=None, phase="1", next=None))
        self.assertFalse((p["state"] / "review.json").exists())

    # ---------------------------------------------------------------- new
    def test_cmd_new_creates_worktree_hidden_and_task_json(self):
        repo = self.stack.enter_context(temp_repo())
        root = Path(os.path.realpath(repo))  # /var is a symlink to /private/var; git reports the real path
        head = git(repo, "rev-parse", "HEAD").strip()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            hx.cmd_new(NS(task="HX-T1", base=None, branch=None, setup=None))
        out = json.loads(buf.getvalue())
        wt = Path(out["worktree"])
        hidden = Path(out["hidden"])
        self.assertTrue((wt / ".git").exists())
        self.assertTrue((wt / "README.md").exists())
        self.assertEqual(root.parent / f"{root.name}-wt" / "HX-T1", wt)
        self.assertEqual(root / ".git" / "hx" / "HX-T1" / "hidden", hidden)
        self.assertTrue(hidden.is_dir())
        meta = json.loads((root / ".git" / "hx" / "HX-T1" / "task.json").read_text())
        self.assertEqual("HX-T1", meta["task"])
        self.assertEqual(head, meta["base"])
        self.assertEqual("hx/HX-T1", meta["branch"])
        self.assertEqual(str(wt), meta["worktree"])
        self.assertEqual("hx/HX-T1", git(wt, "rev-parse", "--abbrev-ref", "HEAD").strip())
        self.assertEqual(head, git(wt, "rev-parse", "HEAD").strip())
        self.assertTrue((repo / ".git" / "hx" / "metrics.jsonl").exists())

    def test_cmd_new_refuses_an_existing_worktree(self):
        self.new_task()
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                hx.cmd_new(NS(task="HX-T1", base=None, branch=None, setup=None))
        self.assertIn("worktree exists", str(cm.exception.code))

    # ---------------------------------------------------------------- call
    def test_run_role_returns_final_text_summary_and_records_the_call(self):
        repo, p = self.new_task()
        spec = self.write_spec(repo)
        fake_dir, env = self.make_fake(event_stream("merhaba"))
        with mock.patch.dict(os.environ, env):
            full, out, line = hx.run_role("worker", "HX-T1", str(spec), reap=False)
        self.assertEqual("merhaba", full)
        self.assertEqual("merhaba", out)
        self.assertTrue(line.startswith("[hx] worker#1 "), line)
        self.assertIn("steps=1", line)
        self.assertIn("out=25", line)
        self.assertIn("1.0s", line)
        self.assertNotIn("TIMEOUT", line)
        raw = (p["state"] / "worker-1.jsonl").read_text(encoding="utf-8")
        self.assertIn("merhaba", raw)
        self.assertIn('"step_finish"', raw)
        calls = read_calls(fake_dir)
        self.assertEqual(1, len(calls))
        self.assertEqual(["run", "-m", hx.CFG["roles"]["worker"]["model"], "--format", "json"],
                         calls[0][:-1])
        metrics = [json.loads(l) for l in (repo / ".git" / "hx" / "metrics.jsonl").read_text().splitlines()]
        call = [m for m in metrics if m.get("event") == "call"][-1]
        self.assertEqual("worker", call["role"])
        self.assertEqual(1, call["n"])
        self.assertEqual(1, call["steps"])
        self.assertEqual(1, call["tool_calls"])
        self.assertEqual(0, call["errors"])
        self.assertEqual("ses_x", call["session"])
        self.assertFalse(call["hidden_access"])

    def test_worker_prompt_hides_the_hidden_section_but_tester_sees_it(self):
        repo, p = self.new_task()
        spec = self.write_spec(repo)
        worker_dir, worker_env = self.make_fake(event_stream("worker metni"))
        with mock.patch.dict(os.environ, worker_env):
            full, _, _ = hx.run_role("worker", "HX-T1", str(spec), reap=False)
        self.assertEqual("worker metni", full)
        worker_prompt = read_calls(worker_dir)[-1][-1]
        self.assertIn("## Kapsam", worker_prompt)
        self.assertNotIn("Gizli test biçimi", worker_prompt)
        self.assertNotIn("gizli ayrıntı", worker_prompt)
        self.assertNotIn(str(p["hidden"]), worker_prompt)

        tester_dir, tester_env = self.make_fake(event_stream("tester metni"))
        with mock.patch.dict(os.environ, tester_env):
            tfull, _, _ = hx.run_role("tester", "HX-T1", str(spec), reap=False)
        self.assertEqual("tester metni", tfull)
        tester_prompt = read_calls(tester_dir)[-1][-1]
        self.assertIn("Gizli test biçimi", tester_prompt)
        self.assertIn("gizli ayrıntı", tester_prompt)
        self.assertIn(str(p["hidden"]), tester_prompt)
        self.assertTrue((p["state"] / "tester-1.jsonl").exists())

    # ---------------------------------------------------------------- gate
    def test_gate_passes_with_exit_zero(self):
        _, p = self.new_task()
        (p["worktree"] / "impl.py").write_text("x = 1\n")
        code, res = self.gate()
        self.assertEqual(0, code)
        self.assertEqual("PASS", res["gate"])
        self.assertEqual(["impl.py"], res["changed"])
        self.assertEqual([], res["out_of_scope"])
        self.assertEqual("pass", res["tests"])
        self.assertFalse((p["state"] / "visible_failure.txt").exists())
        self.assertFalse((p["state"] / "hidden_failure.txt").exists())
        last = json.loads((p["state"] / "last_gate.json").read_text())
        self.assertEqual("PASS", last["gate"])
        self.assertTrue(last["fingerprint"])

    def test_gate_failure_exits_one_and_writes_visible_failure(self):
        _, p = self.new_task()
        code, res = self.gate(test=FAIL_CMD)
        self.assertEqual(1, code)
        self.assertEqual("FAIL", res["gate"])
        self.assertEqual("fail", res["tests"])
        visible = (p["state"] / "visible_failure.txt").read_text(encoding="utf-8")
        self.assertIn("boom", visible)
        self.assertIn("exit 3", visible)
        self.assertIn("boom", (p["state"] / "last_gate.txt").read_text(encoding="utf-8"))
        self.assertFalse((p["state"] / "hidden_failure.txt").exists())

    def test_gate_reports_files_outside_the_allow_list(self):
        _, p = self.new_task()
        wt = p["worktree"]
        (wt / "a.py").write_text("a\n")
        (wt / "b.py").write_text("b\n")
        code, res = self.gate(allow="a.py")
        self.assertEqual(1, code)
        self.assertEqual("FAIL", res["gate"])
        self.assertEqual("pass", res["tests"])
        self.assertEqual(["b.py"], res["out_of_scope"])
        self.assertEqual(["a.py", "b.py"], res["changed"])

    # ---------------------------------------------------------------- commit
    def test_commit_refuses_without_onay(self):
        self.new_task()
        code = self.commit(review="HAYIR")
        self.assertIn("ONAY", str(code))

    def test_commit_refuses_when_the_gate_did_not_pass(self):
        self.new_task()
        code = self.commit()
        self.assertIn("last gate did not pass", str(code))

    def test_commit_refuses_when_the_tree_changed_after_the_gate(self):
        _, p = self.new_task()
        wt = p["worktree"]
        (wt / "impl.py").write_text("v1\n")
        self.gate()
        (wt / "impl.py").write_text("v2\n")
        code = self.commit()
        self.assertIn("changed after the last gate", str(code))

    def test_commit_creates_the_phase_commit_and_handoff(self):
        _, p = self.new_task()
        wt = p["worktree"]
        (wt / "impl.py").write_text("v1\n")
        self.gate()
        self.assertEqual(0, self.record_review())
        with contextlib.redirect_stdout(io.StringIO()):
            hx.cmd_commit(NS(task="HX-T1", m="phase one", review=None, phase="1",
                             next="faz 2: testler"))
        self.assertEqual("phase one", git(wt, "log", "-1", "--format=%s").strip())
        self.assertIn("impl.py", git(wt, "show", "--name-only", "--format=", "HEAD").split())
        head = git(wt, "rev-parse", "HEAD").strip()
        meta = json.loads((p["state"] / "task.json").read_text())
        self.assertEqual(head, meta["base"])
        self.assertEqual(1, len(meta["phases"]))
        self.assertEqual("1", meta["phases"][0]["phase"])
        self.assertEqual(head, meta["phases"][0]["commit"])
        handoff = (p["state"] / "handoff.md").read_text(encoding="utf-8")
        self.assertIn("HX-T1", handoff)
        self.assertIn("hx/HX-T1", handoff)
        self.assertIn("faz 2: testler", handoff)
        self.assertFalse((p["state"] / "last_gate.json").exists())

    # ---------------------------------------------------------------- pair
    def test_cmd_pair_runs_tester_and_worker(self):
        repo, p = self.new_task()
        spec = self.write_spec(repo)
        fake_dir, env = self.make_fake(event_stream("ikisi de bitti"))
        buf = io.StringIO()
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(buf):
            hx.cmd_pair(NS(task="HX-T1", spec=str(spec), max_chars=2500))
        out = buf.getvalue()
        self.assertIn("===== TESTER", out)
        self.assertIn("===== WORKER", out)
        self.assertTrue((p["state"] / "tester-1.jsonl").exists())
        self.assertTrue((p["state"] / "worker-1.jsonl").exists())
        calls = read_calls(fake_dir)
        self.assertEqual(2, len(calls))
        models = sorted(c[2] for c in calls)
        self.assertEqual(sorted([hx.CFG["roles"]["tester"]["model"],
                                 hx.CFG["roles"]["worker"]["model"]]), models)
        metrics = [json.loads(l) for l in (repo / ".git" / "hx" / "metrics.jsonl").read_text().splitlines()]
        roles = sorted(m["role"] for m in metrics if m.get("event") == "call")
        self.assertEqual(["tester", "worker"], roles)

    # ---------------------------------------------------------------- triage
    def test_triage_splits_code_and_test_verdicts(self):
        repo, p = self.new_task()
        spec = self.write_spec(repo)
        (p["state"] / "hidden_failure.txt").write_text("1 hidden test failed\n", encoding="utf-8")
        (p["state"] / "visible_failure.txt").write_text("visible boom\n", encoding="utf-8")
        lines = [json.dumps({"type": "text", "timestamp": 1000, "sessionID": "ses_j",
                             "part": {"messageID": "m1", "text": JUDGE_TEXT}})]
        _, env = self.make_fake(lines)
        with mock.patch.dict(os.environ, env):
            with contextlib.redirect_stdout(io.StringIO()):
                hx.cmd_triage(NS(task="HX-T1", spec=str(spec), max_chars=2500))
        feedback = (p["state"] / "worker_feedback.txt").read_text(encoding="utf-8")
        issues = (p["state"] / "test_issues.txt").read_text(encoding="utf-8")
        self.assertIn("visible boom", feedback)
        self.assertIn("- birinci kural — kod yanlış", feedback)
        self.assertNotIn("test_foo", feedback)
        self.assertNotIn("KOD_HATASI yok", feedback)
        self.assertIn("TEST_HATASI — test_foo — spec dışı", issues)
        self.assertNotIn("birinci kural", issues)
        metrics = [json.loads(l) for l in (repo / ".git" / "hx" / "metrics.jsonl").read_text().splitlines()]
        triage = [m for m in metrics if m.get("event") == "triage"][-1]
        self.assertEqual(1, triage["code_errors"])
        self.assertEqual(1, triage["test_errors"])

    def test_triage_needs_a_hidden_failure(self):
        self.stack.enter_context(temp_repo())
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                hx.cmd_triage(NS(task="HX-T1", spec="spec.md", max_chars=2500))
        self.assertIn("no hidden_failure.txt", str(cm.exception.code))

    # ---------------------------------------------------------------- note / report
    def test_note_and_report_read_metrics(self):
        self.new_task()
        with contextlib.redirect_stdout(io.StringIO()):
            hx.cmd_note(NS(task="HX-T1", kv=["verdict=ONAY", "solved_by=worker"]))
        hx.metric({"task": "HX-T1", "event": "gate", "gate": "FAIL"})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            hx.cmd_report(NS())
        out = buf.getvalue()
        self.assertIn("HX-T1", out)
        self.assertIn("verdict", out)
        self.assertIn("ONAY", out)


if __name__ == "__main__":
    unittest.main()
