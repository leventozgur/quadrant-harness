"""HX-55: PM acceptance tests (`hx tests`), Go budget meter (`hx budget`) and the mechanical phase loop (`hx auto`).

The fake `opencode` never talks to the network; the budget meter reads a throwaway SQLite file, never the real one.
"""
import contextlib
import io
import json
import os
import shutil
import sqlite3
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
src/**
"""

PASS_CMD = 'python3 -c "pass"'


class NS:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def event_stream(text="bitti"):
    return [
        json.dumps({"type": "step_start", "timestamp": 1000, "sessionID": "ses_a", "part": {"messageID": "m1"}}),
        json.dumps({"type": "text", "timestamp": 1200, "sessionID": "ses_a", "part": {"messageID": "m1", "text": text}}),
        json.dumps({"type": "step_finish", "timestamp": 1500, "sessionID": "ses_a",
                    "part": {"tokens": {"input": 10, "output": 5}}}),
    ]


def seq_cmd(path, failing_runs, text):
    """Fails (printing `text`) on the listed 0-based runs, passes otherwise; run counter kept in `path`."""
    return (f"python3 -c \"import pathlib,sys; p=pathlib.Path('{path}'); n=int(p.read_text()) if p.exists() else 0; "
            f"p.write_text(str(n+1)); bad=n in {sorted(failing_runs)}; print('{text}' if bad else 'ok'); sys.exit(1 if bad else 0)\"")


def counter_cmd(path, pass_from):
    """A test command that fails until it has run `pass_from` times before (counter kept in `path`)."""
    return (f"python3 -c \"import pathlib,sys; p=pathlib.Path('{path}'); n=int(p.read_text()) if p.exists() else 0; "
            f"p.write_text(str(n+1)); print('visible boom', n); sys.exit(0 if n >= {pass_from} else 1)\"")


class FailingNamesTest(unittest.TestCase):
    def test_tap_unittest_pytest_dotnet(self):
        log = "\n".join([
            "TAP version 13",
            "not ok 1 - boş girdi boş liste döner",
            "  ---", "  expected: 3", "  actual: 4",
            "    not ok 2 - eşitlikte sol taraf kazanır",
            "not ok 3 - bekleyen # TODO later",
            "not ok 4 - atlanan # SKIP",
            "ok 5 - geçen",
            "FAIL: test_negatif_reddedilir (test_x.T.test_negatif_reddedilir)",
            "Negatif tutar ValueError verir.",
            "----------------------------------------------------------------------",
            "ERROR: test_yol (test_x.T.test_yol)",
            "Traceback (most recent call last):",
            "FAILED tests/test_y.py::test_yuvarlama - AssertionError: 1.25 != 1.3",
            "  Failed Ns.Cls.TarihAraligi [12 ms]",
            "not ok 1 - boş girdi boş liste döner",
        ])
        self.assertEqual(["boş girdi boş liste döner", "eşitlikte sol taraf kazanır",
                          "test_negatif_reddedilir — Negatif tutar ValueError verir.", "test_yol",
                          "test_yuvarlama", "Ns.Cls.TarihAraligi"], hx.failing_test_names(log))

    def test_realpath_and_parameters_masked(self):
        d = tempfile.mkdtemp(prefix="hx-mask-")
        self.addCleanup(shutil.rmtree, d, True)
        real = os.path.realpath(d)
        names = hx.failing_test_names(f"not ok 1 - {real}/a.mjs\nFAILED t.py::test_kur[girdi-5] - x\nnot ok 3 - [5]", d)
        self.assertEqual(["<gizli>/a.mjs", "test_kur"], names)

    def test_no_assertion_text_and_hidden_path_masked(self):
        names = hx.failing_test_names("not ok 1 - /h/hidden/a.test.mjs\nFAILED x.py::t - expected 5 got 6", "/h/hidden")
        self.assertEqual(["<gizli>/a.test.mjs", "t"], names)
        self.assertFalse(any("expected" in n for n in names))

    def test_limit_and_empty(self):
        self.assertEqual([], hx.failing_test_names(""))
        log = "\n".join(f"not ok {i} - t{i}" for i in range(40))
        self.assertEqual(20, len(hx.failing_test_names(log)))


class BudgetTest(unittest.TestCase):
    def db(self, rows):
        d = tempfile.mkdtemp(prefix="hx-db-")
        self.addCleanup(shutil.rmtree, d, True)
        path = Path(d) / "opencode.db"
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE session_message (id text, session_id text, type text, seq integer, "
                    "time_created integer, time_updated integer, data text)")
        for i, (age_s, provider, model, tokens, typ) in enumerate(rows):
            data = {"model": {"id": model, "providerID": provider}, "tokens": tokens}
            con.execute("INSERT INTO session_message VALUES (?,?,?,?,?,?,?)",
                        (str(i), "s", typ, i, int((self.now - age_s) * 1000), 0, json.dumps(data)))
        con.commit(); con.close()
        return str(path)

    def setUp(self):
        self.now = 2_000_000_000.0
        self.tok = {"input": 1_000_000, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}}

    def test_windows_provider_and_type(self):
        price = hx.CFG["prices"]["opencode-go/deepseek-v4.1-flash"]["input"]
        path = self.db([
            (60, "opencode-go", "deepseek-v4.1-flash", self.tok, "assistant"),            # all windows
            (3 * 86400, "opencode-go", "deepseek-v4.1-flash", self.tok, "assistant"),     # 7d and 30d
            (20 * 86400, "opencode-go", "deepseek-v4.1-flash", self.tok, "assistant"),    # 30d
            (40 * 86400, "opencode-go", "deepseek-v4.1-flash", self.tok, "assistant"),    # outside
            (60, "opencode", "deepseek-v4.1-flash-free", self.tok, "assistant"),          # other provider: free
            (60, "opencode-go", "deepseek-v4.1-flash", self.tok, "user"),                 # not a model request
        ])
        spend = hx.go_spend(now=self.now, db=path)
        self.assertEqual({"5h": round(price, 2), "7d": round(2 * price, 2), "30d": round(3 * price, 2)}, spend)

    def test_missing_db_is_none_and_line_says_so(self):
        self.assertIsNone(hx.go_spend(db="/nonexistent/opencode.db"))
        with mock.patch.object(hx, "go_spend", lambda: None):
            self.assertIn("not readable", hx.budget_line())

    def test_warning_threshold(self):
        with mock.patch.dict(hx.CFG, {"budget": {"limits_usd": {"5h": 10, "7d": 30, "30d": 60}, "warn_at": 0.8}}):
            line = hx.budget_line({"5h": 1.0, "7d": 25.0, "30d": 30.0})
        self.assertIn("7d $25.00/$30 (83%)", line)
        self.assertIn("WARNING: 7d", line)
        self.assertNotIn("5h,", line)


class AutoBase(unittest.TestCase):
    task = "HX-A1"
    mode = "pm"

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.dict(hx.CFG, {"rate_limit_wait_s": 0, "tester_mode": self.mode,
                                                          "auto_escalate": True, "max_worker_retries": 2}))
        self.stack.enter_context(mock.patch.object(hx.time, "sleep", lambda *_: None))
        self.stack.enter_context(mock.patch.object(hx, "reap_orphans", lambda *_, **__: 0))
        self.stack.enter_context(mock.patch.object(hx, "go_spend", lambda *a, **k: {"5h": 0.0, "7d": 0.0, "30d": 0.0}))
        self.repo = self.stack.enter_context(temp_repo())
        with contextlib.redirect_stdout(io.StringIO()):
            hx.cmd_new(NS(task=self.task, base=None, branch=None, setup=None))
        self.p = hx.task_paths(self.task)
        self.spec = Path(self.repo).parent / "spec.md"
        self.spec.write_text(SPEC_TEXT, encoding="utf-8")
        self.fake_dir = tempfile.mkdtemp(prefix="hx-fake-")
        self.addCleanup(shutil.rmtree, self.fake_dir, True)
        self.stack.enter_context(mock.patch.dict(os.environ, fake_opencode(self.fake_dir, event_stream())))
        self.cnt = Path(self.fake_dir) / "cnt"

    def write_tests(self):
        (self.p["hidden"] / "a.test.mjs").write_text("// SECRET_TEST_BODY\n", encoding="utf-8")

    def auto(self, **kw):
        args = dict(task=self.task, spec=str(self.spec), test=None, hidden_cmd=None, allow="**", protect=None,
                    no_tests=False, retry=0, gate_timeout=60, fresh=False, feedback=None)
        args.update(kw)
        out = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                hx.cmd_auto(NS(**args))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue()

    def prompts(self):
        return [c[-1] for c in read_calls(self.fake_dir)]

    def events(self, kind):
        mp = self.p["state"].parent / "metrics.jsonl"
        return [json.loads(l) for l in mp.read_text().splitlines() if l.strip() and json.loads(l).get("event") == kind]


class AutoTest(AutoBase):
    def test_pass_first_round_writes_diff_and_summary(self):
        code, out = self.auto(test=PASS_CMD)
        self.assertEqual(0, code, out)
        self.assertEqual(1, len(read_calls(self.fake_dir)))
        self.assertIn("PASS — worker×1 escalate×0 gates 1 (0 fail)", out)
        self.assertTrue((self.p["state"] / "review.diff").exists())
        self.assertIn("next: blind review", out)
        self.assertNotIn("bitti", out)  # the worker's report stays in the state directory
        self.assertTrue(list(self.p["state"].glob("auto_worker_1_report.txt")))
        self.assertEqual("PASS", self.events("auto")[-1]["status"])

    def test_visible_failure_is_fed_back_then_pass(self):
        code, out = self.auto(test=counter_cmd(self.cnt, 1))
        self.assertEqual(0, code, out)
        prompts = self.prompts()
        self.assertEqual(2, len(prompts))
        self.assertIn("visible boom 0", prompts[1])
        self.assertIn("gates 2 (1 fail)", out)

    def test_hidden_names_fed_back_without_test_code_then_same_fail_stops(self):
        self.write_tests()
        hidden = "python3 -c \"print('not ok 1 - boş girdi boş liste döner'); print('  expected: 7'); raise SystemExit(1)\""
        code, out = self.auto(test=PASS_CMD, hidden_cmd=hidden)
        self.assertEqual(4, code, out)
        self.assertIn("SAME_HIDDEN_FAIL", out)
        prompts = self.prompts()
        self.assertEqual(2, len(prompts))
        self.assertIn("boş girdi boş liste döner", prompts[1])
        self.assertNotIn("expected: 7", prompts[1])
        self.assertNotIn("SECRET_TEST_BODY", prompts[1])

    def test_retries_exhausted_after_escalate(self):
        code, out = self.auto(test="echo nope; exit 1")
        self.assertEqual(5, code, out)
        self.assertIn("RETRIES_EXHAUSTED", out)
        roles = [r["role"] for r in self.events("call")]
        self.assertEqual(["worker", "worker", "worker", "escalate"], roles)

    def test_no_escalate_when_disabled(self):
        with mock.patch.dict(hx.CFG, {"auto_escalate": False}):
            code, out = self.auto(test="echo nope; exit 1")
        self.assertEqual(5, code)
        self.assertEqual(["worker"] * 3, [r["role"] for r in self.events("call")])

    def test_out_of_scope_feedback(self):
        (self.p["worktree"] / "stray.txt").write_text("x", encoding="utf-8")
        code, out = self.auto(test=PASS_CMD, allow="src/**")
        self.assertEqual(5, code, out)
        fb = (self.p["state"] / "auto_feedback_1.txt").read_text()
        self.assertIn("stray.txt", fb)
        self.assertIn("kapsam dışı", fb)

    def test_hidden_cmd_needs_tests(self):
        code, out = self.auto(test=PASS_CMD, hidden_cmd=PASS_CMD)
        self.assertIn("is empty", str(code) + out)
        self.assertEqual([], read_calls(self.fake_dir))

    def test_existing_worker_call_is_not_repeated(self):
        with contextlib.redirect_stdout(io.StringIO()):
            hx.run_role("worker", self.task, str(self.spec))
        code, out = self.auto(test=PASS_CMD)
        self.assertEqual(0, code, out)
        self.assertEqual(1, len(read_calls(self.fake_dir)))

    def test_feedback_runs_a_worker_round_first(self):
        with contextlib.redirect_stdout(io.StringIO()):
            hx.run_role("worker", self.task, str(self.spec))
        fb = Path(self.fake_dir) / "fb.txt"
        fb.write_text("denetçi bulgusu: sınır kontrolü eksik", encoding="utf-8")
        code, out = self.auto(test=PASS_CMD, feedback=str(fb))
        self.assertEqual(0, code, out)
        prompts = self.prompts()
        self.assertEqual(2, len(prompts))
        self.assertIn("denetçi bulgusu", prompts[1])

    def test_missing_feedback_file(self):
        code, _ = self.auto(test=PASS_CMD, feedback="/nonexistent/fb.txt")
        self.assertIn("feedback file not found", str(code))
        self.assertEqual([], read_calls(self.fake_dir))

    def test_gate_retry_line_before_json_still_feeds_back(self):
        code, out = self.auto(test=counter_cmd(self.cnt, 2), retry=1)  # gate 1 fails twice (retry), gate 2 passes
        self.assertEqual(0, code, out)
        self.assertEqual(2, len(self.prompts()))
        self.assertIn("visible boom", self.prompts()[1])

    def test_missing_allow_or_tests_refused_before_any_call(self):
        code, _ = self.auto(test=PASS_CMD, allow=None)
        self.assertIn("--allow", str(code))
        code, _ = self.auto(test=None)
        self.assertIn("--test", str(code))
        self.assertEqual([], read_calls(self.fake_dir))

    def test_timeout_resumes_once(self):
        seen = []

        def fake_run_role(role, task, spec, feedback=None, resume=False, **kw):
            seen.append((role, resume))
            st = hx.task_paths(task)["state"]
            n = len([f for f in st.glob(f"{role}-*.jsonl")]) + 1
            (st / f"{role}-{n}.jsonl").write_text("")
            hx.metric({"task": task, "event": "call", "role": role, "resumed": resume})
            return "", "rapor", f"[hx] {role}#{n} m cost≈$0.01" + ("" if resume else " TIMEOUT(10s; continue with --resume)")
        with mock.patch.object(hx, "run_role", fake_run_role):
            code, out = self.auto(test=PASS_CMD)
        self.assertEqual(0, code, out)
        self.assertEqual([("worker", False), ("worker", True)], seen)
        self.assertIn("Go≈$0.020", out)

    def test_feedback_with_used_worker_budget_goes_to_escalate(self):
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(3):
                hx.run_role("worker", self.task, str(self.spec))
        fb = Path(self.fake_dir) / "fb.txt"
        fb.write_text("kural", encoding="utf-8")
        code, out = self.auto(test=PASS_CMD, feedback=str(fb))
        self.assertEqual(0, code, out)
        self.assertEqual(["worker"] * 3 + ["escalate"], [r["role"] for r in self.events("call")])
        code, out = self.auto(test="exit 1", feedback=str(fb))
        self.assertEqual(5, code)
        self.assertEqual("RETRIES_EXHAUSTED", self.events("auto")[-1]["status"])

    def test_same_hidden_fail_only_for_consecutive_rounds(self):
        self.write_tests()
        vis = seq_cmd(Path(self.fake_dir) / "v", [1], "visible boom")
        hid = seq_cmd(Path(self.fake_dir) / "h", [0, 2], "not ok 1 - kural bir")
        code, out = self.auto(test=vis, hidden_cmd=hid)
        self.assertEqual(0, code, out)
        self.assertNotIn("SAME_HIDDEN_FAIL", out)
        self.assertEqual(["worker", "worker", "worker", "escalate"], [r["role"] for r in self.events("call")])

    def test_hidden_access_stops(self):
        (self.p["state"] / "hidden_access.json").write_text(json.dumps({"role": "worker", "n": 1, "paths": []}))
        code, out = self.auto(test=PASS_CMD)
        self.assertEqual(3, code, out)
        self.assertIn("HIDDEN_ACCESS", out)


class AutoModelModeTest(AutoBase):
    mode = "model"

    def test_hidden_fail_hands_over_to_triage(self):
        self.write_tests()
        code, out = self.auto(test=PASS_CMD, hidden_cmd="echo 'not ok 1 - x'; exit 1")
        self.assertEqual(4, code)
        self.assertIn("hx triage", out)
        self.assertEqual(1, len(read_calls(self.fake_dir)))


class TestsCommandTest(AutoBase):
    def run_tests(self, fresh=False):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                hx.cmd_tests(NS(task=self.task, fresh=fresh))
                return 0, out.getvalue()
            except SystemExit as e:
                return e.code, out.getvalue()

    def test_empty_suite_refused(self):
        code, _ = self.run_tests()
        self.assertIn("no acceptance tests", str(code))

    def test_flag_records_suite_hash_and_fresh_compares_with_it(self):
        self.write_tests()
        self.run_tests()
        flag = self.p["state"] / "hidden_access.json"
        # a model call changed the suite and was flagged; registering it again must not make --fresh pass
        (self.p["hidden"] / "a.test.mjs").write_text("// touched by a model\n", encoding="utf-8")
        flag.write_text(json.dumps({"suite_sha256": hx.hidden_suite(self.p)[1]}))
        self.run_tests()
        code, _ = self.run_tests(fresh=True)
        self.assertIn("same as when", str(code))
        self.assertTrue(flag.exists())
        (self.p["hidden"] / "a.test.mjs").write_text("// rewritten by the PM\n", encoding="utf-8")
        self.run_tests()  # a plain registration first is fine: the comparison is with the flagged suite
        code, _ = self.run_tests(fresh=True)
        self.assertEqual(0, code)
        self.assertFalse(flag.exists())

    def test_fresh_refused_when_suite_unchanged(self):
        self.write_tests()
        self.run_tests()
        flag = self.p["state"] / "hidden_access.json"
        flag.write_text("{}")
        code, _ = self.run_tests(fresh=True)
        self.assertIn("same as when", str(code))
        self.assertTrue(flag.exists())
        (self.p["hidden"] / "a.test.mjs").write_text("// rewritten\n", encoding="utf-8")
        code, out = self.run_tests(fresh=True)
        self.assertEqual(0, code)
        self.assertFalse(flag.exists())

    def test_register_and_fresh_clears_flag(self):
        self.write_tests()
        flag = self.p["state"] / "hidden_access.json"
        flag.write_text("{}")
        code, out = self.run_tests()
        self.assertEqual(0, code)
        self.assertTrue(flag.exists())
        self.assertIn("1 file(s)", out)
        (self.p["hidden"] / "a.test.mjs").write_text("// rewritten\n", encoding="utf-8")
        code, out = self.run_tests(fresh=True)
        self.assertFalse(flag.exists())
        self.assertIn("flag cleared", out)
        ev = self.events("pm_tests")
        self.assertEqual([False, True], [e["fresh"] for e in ev])
        self.assertNotEqual(ev[0]["suite_sha256"], ev[1]["suite_sha256"])


if __name__ == "__main__":
    unittest.main()
