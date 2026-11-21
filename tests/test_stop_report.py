"""HX-32: STOP file stops new calls/pairs; `hx report --since` quality signals and threshold warnings."""
import contextlib
import io
import json
import time
import unittest
from unittest import mock

import hx
from tests.helpers import temp_repo


class NS:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def rec(task, event, **kw):
    return {"task": task, "event": event, "ts": "2026-11-20T10:00:00Z", **kw}


class StopFileTest(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(temp_repo())

    def test_call_refuses_while_stop_exists(self):
        (hx.state_dir() / "STOP").write_text("bakım\n")
        with mock.patch.object(hx, "run_role") as run:
            with self.assertRaises(SystemExit) as cm:
                hx.cmd_call(NS(task="HX-S1", role="worker", spec="s.md", feedback=None, model=None,
                               read_only=False, max_chars=100, timeout=None, resume=False, force_retry=False))
        self.assertIn("STOP file present", str(cm.exception.code))
        self.assertIn("bakım", str(cm.exception.code))
        run.assert_not_called()

    def test_pair_refuses_while_stop_exists(self):
        (hx.state_dir() / "STOP").write_text("")
        with mock.patch.object(hx, "run_role") as run:
            with self.assertRaises(SystemExit) as cm:
                hx.cmd_pair(NS(task="HX-S1", spec="s.md", max_chars=100))
        self.assertIn("STOP file present", str(cm.exception.code))
        run.assert_not_called()

    def test_check_stop_passes_without_the_file(self):
        hx.check_stop()  # no exception
        stop = hx.state_dir() / "STOP"
        stop.write_text("x")
        stop.unlink()
        hx.check_stop()


class SummaryTest(unittest.TestCase):
    def test_first_round_pass_counts_the_first_gate_of_each_phase(self):
        rs = [rec("A", "gate", gate="FAIL"), rec("A", "gate", gate="PASS"), rec("A", "phase_commit"),
              rec("A", "gate", gate="PASS"), rec("B", "gate", gate="PASS")]
        sm = hx.report_summary(rs)
        self.assertEqual(3, sm["first_round_gates"])
        self.assertAlmostEqual(2 / 3, sm["first_round_pass"])
        self.assertTrue(any("first-round gate pass" in w for w in sm["warnings"]) is False)

    def test_low_first_round_pass_warns(self):
        rs = [rec("A", "gate", gate="FAIL"), rec("B", "gate", gate="FAIL"), rec("C", "gate", gate="PASS")]
        sm = hx.report_summary(rs)
        self.assertTrue(any("first-round gate pass 33%" in w for w in sm["warnings"]), sm["warnings"])

    def test_review_rejection_uses_review_records_and_is_na_without_them(self):
        self.assertIsNone(hx.report_summary([rec("A", "gate", gate="PASS")])["review_reject"])
        rs = [rec("A", "review", verdict="RED"), rec("A", "review", verdict="ONAY"), rec("B", "review", verdict="RED")]
        sm = hx.report_summary(rs)
        self.assertAlmostEqual(2 / 3, sm["review_reject"])
        self.assertTrue(any("reviewer rejection" in w for w in sm["warnings"]))

    def test_calls_escalation_timeouts_hidden_access_and_belirsiz(self):
        rs = [rec("A", "call", role="worker"), rec("A", "call", role="escalate", timeout=True),
              rec("B", "call", role="worker", stalled=True, hidden_access=True, ha_v=2),
              rec("B", "call", role="tester"), rec("A", "triage", unclear=2), rec("B", "triage", code_errors=1)]
        sm = hx.report_summary(rs)
        self.assertEqual(4, sm["calls"])
        self.assertEqual(1, sm["escalated_tasks"])
        self.assertEqual(2, sm["timeout_stalled"])
        self.assertEqual(1, sm["hidden_access"])
        self.assertEqual(2, sm["belirsiz"])
        joined = " ".join(sm["warnings"])
        self.assertIn("hidden_access on 1 calls", joined)
        self.assertIn("TIMEOUT/STALLED 2/4", joined)
        self.assertIn("escalated 1/2", joined)

    def test_thresholds_can_be_overridden_and_empty_input_is_clean(self):
        sm = hx.report_summary([rec("A", "call", role="worker", hidden_access=True, ha_v=2)], {"hidden_access_max": 5})
        self.assertEqual([], sm["warnings"])
        sm = hx.report_summary([])
        self.assertEqual([], sm["warnings"])
        self.assertIsNone(sm["first_round_pass"])


class HiddenAccessVersionTest(unittest.TestCase):
    def test_records_without_ha_v_are_legacy_and_do_not_warn(self):
        sm = hx.report_summary([rec("A", "call", role="worker", hidden_access=True),
                                rec("B", "call", role="worker", hidden_access=True, ha_v=1),
                                rec("C", "call", role="worker", hidden_access=False, ha_v=2)])
        self.assertEqual(0, sm["hidden_access"])
        self.assertEqual(2, sm["hidden_access_legacy"])
        self.assertFalse(any("hidden_access" in w for w in sm["warnings"]))

    def test_new_records_count_and_warn_and_the_report_shows_legacy_separately(self):
        rs = [rec("A", "call", role="worker", hidden_access=True), rec("B", "call", role="worker", hidden_access=True, ha_v=2)]
        sm = hx.report_summary(rs)
        self.assertEqual(1, sm["hidden_access"])
        self.assertTrue(any("hidden_access on 1 calls" in w for w in sm["warnings"]))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            hx.print_report_summary(sm, None)
        self.assertIn("hidden_access calls:   1", buf.getvalue())
        self.assertIn("+1 older hidden_access flags", buf.getvalue())


class SinceTest(unittest.TestCase):
    def test_parse_since(self):
        self.assertIsNone(hx.parse_since(None))
        for text, secs in (("12h", 43200), ("7d", 604800), ("2w", 1209600)):
            cut = hx.parse_since(text)
            got = time.mktime(time.strptime(cut, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
            self.assertLess(abs((time.time() - got) - secs), 5)
        with self.assertRaises(SystemExit):
            hx.parse_since("soon")

    def test_report_since_filters_old_records(self):
        with temp_repo():
            hx.metric({"task": "NEW", "event": "gate", "gate": "PASS", "n_changed": 1})
            with open(hx.state_dir() / "metrics.jsonl", "a") as f:
                f.write(json.dumps({"task": "OLD", "event": "gate", "gate": "FAIL", "ts": "2020-01-01T00:00:00Z"}) + "\n")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                hx.cmd_report(NS(since="7d"))
            out = buf.getvalue()
            self.assertIn("NEW", out)
            self.assertNotIn("OLD", out)
            self.assertIn("since 7d", out)
            self.assertIn("first-round gate pass: 100%", out)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                hx.cmd_report(NS(since=None))
            self.assertIn("OLD", buf.getvalue())
            self.assertIn("all time", buf.getvalue())

    def test_report_prints_warning_lines(self):
        with temp_repo():
            hx.metric({"task": "T", "event": "gate", "gate": "FAIL", "n_changed": 1})
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                hx.cmd_report(NS(since="1d"))
            self.assertIn("WARNING: first-round gate pass 0%", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
