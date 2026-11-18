"""Rate-limit retry policy (HX-23) and cmd_pair role failures (HX-24).

The fake `opencode` never talks to the network; `hx.CFG["rate_limit_wait_s"]` is forced to 0 so no test waits.
"""
import contextlib
import io
import json
import os
import shutil
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


class NS:
    """Minimal argparse.Namespace stand-in for the cmd_* handlers."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def step_start(timestamp=1000):
    return json.dumps({"type": "step_start", "timestamp": timestamp, "sessionID": "ses_x",
                       "part": {"messageID": "m1"}})


def text_event(text, timestamp=1200):
    return json.dumps({"type": "text", "timestamp": timestamp, "sessionID": "ses_x",
                       "part": {"messageID": "m1", "text": text}})


def step_finish(timestamp=1500):
    return json.dumps({"type": "step_finish", "timestamp": timestamp, "sessionID": "ses_x",
                       "part": {"tokens": {"input": 10, "output": 5}}})


class Base(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        # no real 90 s sleeps; patch.dict restores the original config value afterwards
        self.stack.enter_context(mock.patch.dict(hx.CFG, {"rate_limit_wait_s": 0}))
        # run_streaming polls every 2 s; the fake opencode exits instantly, so skip that idle wait in tests
        self.stack.enter_context(mock.patch.object(hx.time, "sleep", lambda *_: None))

    def new_task(self, task="HX-T2"):
        repo = self.stack.enter_context(temp_repo())
        with contextlib.redirect_stdout(io.StringIO()):
            hx.cmd_new(NS(task=task, base=None, branch=None, setup=None))
        return repo, hx.task_paths(task)

    def write_spec(self, repo):
        spec = Path(repo).parent / "spec.md"
        spec.write_text(SPEC_TEXT, encoding="utf-8")
        return spec

    def make_fake(self, lines, **kwargs):
        directory = tempfile.mkdtemp(prefix="hx-fake-")
        self.addCleanup(shutil.rmtree, directory, True)
        return directory, fake_opencode(directory, lines, **kwargs)

    def call_metrics(self, repo):
        path = repo / ".git" / "hx" / "metrics.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines() if json.loads(l).get("event") == "call"]


class RateLimitRetryTest(Base):
    def test_stderr_rate_limit_without_step_finish_retries_three_times(self):
        repo, p = self.new_task()
        spec = self.write_spec(repo)
        fake_dir, env = self.make_fake([step_start(), text_event("başlıyorum")],
                                       exit_code=1, stderr="error: 429 Too Many Requests\n")
        with mock.patch.dict(os.environ, env):
            hx.run_role("worker", "HX-T2", str(spec), reap=False)
        self.assertEqual(4, len(read_calls(fake_dir)))
        for k in (1, 2, 3):
            self.assertTrue((p["state"] / f"worker-1.attempt{k}.jsonl").exists(), k)
        self.assertFalse((p["state"] / "worker-1.attempt4.jsonl").exists())
        self.assertTrue((p["state"] / "worker-1.jsonl").exists())
        self.assertEqual(4, self.call_metrics(repo)[-1]["attempts"])

    def test_signal_inside_an_error_event_line_retries(self):
        repo, _ = self.new_task()
        spec = self.write_spec(repo)
        lines = [step_start(),
                 json.dumps({"type": "error", "timestamp": 1100, "sessionID": "ses_x",
                             "part": {"error": "Usage limit reached for this account"}})]
        fake_dir, env = self.make_fake(lines, exit_code=1)
        with mock.patch.dict(os.environ, env):
            hx.run_role("worker", "HX-T2", str(spec), reap=False)
        self.assertEqual(4, len(read_calls(fake_dir)))

    def test_nested_error_type_rate_limit_error_retries(self):
        repo, p = self.new_task()
        spec = self.write_spec(repo)
        lines = [step_start(),
                 json.dumps({"type": "error", "timestamp": 1100, "sessionID": "ses_x",
                             "error": {"type": "rate_limit_error", "message": "slow down"}})]
        fake_dir, env = self.make_fake(lines, exit_code=1)
        with mock.patch.dict(os.environ, env):
            hx.run_role("worker", "HX-T2", str(spec), reap=False)
        self.assertEqual(4, len(read_calls(fake_dir)))
        self.assertEqual(4, self.call_metrics(repo)[-1]["attempts"])

    def test_nested_error_type_with_no_step_finish_retries(self):
        repo, p = self.new_task()
        spec = self.write_spec(repo)
        lines = [step_start(),
                 json.dumps({"type": "error", "timestamp": 1100,
                             "error": {"type": "rate_limit_error", "message": "slow down"}})]
        fake_dir, env = self.make_fake(lines, exit_code=1)
        with mock.patch.dict(os.environ, env):
            hx.run_role("worker", "HX-T2", str(spec), reap=False)
        self.assertEqual(0, self.call_metrics(repo)[-1]["steps"])
        self.assertEqual(4, len(read_calls(fake_dir)))
        self.assertEqual(4, self.call_metrics(repo)[-1]["attempts"])

    def test_rate_limit_with_an_underscore_in_stderr_retries(self):
        repo, _ = self.new_task()
        spec = self.write_spec(repo)
        fake_dir, env = self.make_fake([step_start()], exit_code=1, stderr="provider: rate_limit_exceeded\n")
        with mock.patch.dict(os.environ, env):
            hx.run_role("worker", "HX-T2", str(spec), reap=False)
        self.assertEqual(4, len(read_calls(fake_dir)))

    def test_too_many_requests_and_case_insensitive_stderr_retry(self):
        repo, _ = self.new_task()
        spec = self.write_spec(repo)
        fake_dir, env = self.make_fake([step_start()], exit_code=1, stderr="RATE LIMIT hit\n")
        with mock.patch.dict(os.environ, env):
            hx.run_role("worker", "HX-T2", str(spec), reap=False)
        self.assertEqual(4, len(read_calls(fake_dir)))

    def test_successful_call_mentioning_rate_limit_in_text_is_not_retried(self):
        repo, p = self.new_task()
        spec = self.write_spec(repo)
        lines = [step_start(), text_event("bir rate limit yazıyorum, usage limit ve 429"), step_finish()]
        fake_dir, env = self.make_fake(lines)
        with mock.patch.dict(os.environ, env):
            full, _, _ = hx.run_role("worker", "HX-T2", str(spec), reap=False)
        self.assertEqual("bir rate limit yazıyorum, usage limit ve 429", full)
        self.assertEqual(1, len(read_calls(fake_dir)))
        self.assertEqual([], sorted(p["state"].glob("worker-1.attempt*.jsonl")))
        self.assertEqual(1, self.call_metrics(repo)[-1]["attempts"])

    def test_tool_event_text_never_triggers_a_retry(self):
        repo, _ = self.new_task()
        spec = self.write_spec(repo)
        lines = [step_start(),
                 json.dumps({"type": "tool_use", "timestamp": 1100, "sessionID": "ses_x",
                             "part": {"tool": "write", "state": {"input": {"content": "rate limit 429"}}}})]
        fake_dir, env = self.make_fake(lines)
        with mock.patch.dict(os.environ, env):
            hx.run_role("worker", "HX-T2", str(spec), reap=False)
        self.assertEqual(1, len(read_calls(fake_dir)))

    def test_tool_output_text_never_triggers_a_retry(self):
        repo, _ = self.new_task()
        spec = self.write_spec(repo)
        lines = [step_start(),
                 json.dumps({"type": "tool", "timestamp": 1100, "sessionID": "ses_x",
                             "part": {"tool": "bash", "state": {"output": "usage limit 429"}}})]
        fake_dir, env = self.make_fake(lines)
        with mock.patch.dict(os.environ, env):
            hx.run_role("worker", "HX-T2", str(spec), reap=False)
        self.assertEqual(1, len(read_calls(fake_dir)))

    def test_text_event_signal_alone_never_retries_even_on_a_failing_exit(self):
        repo, p = self.new_task()
        spec = self.write_spec(repo)
        lines = [step_start(), text_event("HTTP 429 rate limit, usage limit")]
        fake_dir, env = self.make_fake(lines, exit_code=1)
        with mock.patch.dict(os.environ, env):
            hx.run_role("worker", "HX-T2", str(spec), reap=False)
        self.assertEqual(1, len(read_calls(fake_dir)))
        self.assertEqual(1, self.call_metrics(repo)[-1]["attempts"])
        self.assertEqual([], sorted(p["state"].glob("worker-1.attempt*.jsonl")))

    def test_stderr_signal_with_a_finished_step_is_not_retried(self):
        repo, p = self.new_task()
        spec = self.write_spec(repo)
        lines = [step_start(), text_event("bitti"), step_finish()]
        fake_dir, env = self.make_fake(lines, exit_code=1, stderr="429 Too Many Requests\n")
        with mock.patch.dict(os.environ, env):
            hx.run_role("worker", "HX-T2", str(spec), reap=False)
        self.assertEqual(1, len(read_calls(fake_dir)))
        self.assertEqual(1, self.call_metrics(repo)[-1]["attempts"])
        self.assertEqual([], sorted(p["state"].glob("worker-1.attempt*.jsonl")))

    def test_previous_attempt_raw_is_kept_in_the_attempt_file(self):
        repo, p = self.new_task()
        spec = self.write_spec(repo)
        fake_dir, env = self.make_fake([step_start(), text_event("ilk deneme")],
                                       exit_code=1, stderr="rate limit\n")
        with mock.patch.dict(os.environ, env):
            hx.run_role("worker", "HX-T2", str(spec), reap=False)
        kept = (p["state"] / "worker-1.attempt1.jsonl").read_text()
        self.assertEqual(Path(fake_dir, "stdout.txt").read_text(), kept)

    def test_unrelated_stderr_error_is_not_retried(self):
        repo, _ = self.new_task()
        spec = self.write_spec(repo)
        fake_dir, env = self.make_fake([step_start()], exit_code=1, stderr="model not found\n")
        with mock.patch.dict(os.environ, env):
            hx.run_role("worker", "HX-T2", str(spec), reap=False)
        self.assertEqual(1, len(read_calls(fake_dir)))

    def test_metadata_containing_429_does_not_retry_an_unrelated_error(self):
        repo, p = self.new_task()
        spec = self.write_spec(repo)
        lines = [step_start(),
                 json.dumps({"type": "error", "timestamp": 1795004290000, "sessionID": "ses_429_x",
                             "part": {"messageID": "msg_429", "message": "model not found"}})]
        fake_dir, env = self.make_fake(lines, exit_code=1)
        with mock.patch.dict(os.environ, env):
            hx.run_role("worker", "HX-T2", str(spec), reap=False)
        self.assertEqual(1, len(read_calls(fake_dir)))
        self.assertEqual(1, self.call_metrics(repo)[-1]["attempts"])
        self.assertEqual([], sorted(p["state"].glob("worker-1.attempt*.jsonl")))

    def test_nested_metadata_containing_429_does_not_retry_an_unrelated_error(self):
        repo, p = self.new_task()
        spec = self.write_spec(repo)
        lines = [step_start(),
                 json.dumps({"type": "error", "timestamp": 1795004290000, "sessionID": "ses_429_x",
                             "error": {"name": "APIError", "data": {"messageID": "msg_429",
                                                                    "timestamp": 1795004290000,
                                                                    "message": "model not found"}},
                             "part": {"message": "model not found"}})]
        fake_dir, env = self.make_fake(lines, exit_code=1)
        with mock.patch.dict(os.environ, env):
            hx.run_role("worker", "HX-T2", str(spec), reap=False)
        self.assertEqual(1, len(read_calls(fake_dir)))
        self.assertEqual(1, self.call_metrics(repo)[-1]["attempts"])
        self.assertEqual([], sorted(p["state"].glob("worker-1.attempt*.jsonl")))

    def test_nested_payload_field_with_429_is_kept_and_retries(self):
        repo, p = self.new_task()
        spec = self.write_spec(repo)
        lines = [step_start(),
                 json.dumps({"type": "error", "timestamp": 1100, "sessionID": "ses_x",
                             "error": {"name": "APIError",
                                       "data": {"statusCode": 429, "message": "slow down"}}})]
        fake_dir, env = self.make_fake(lines, exit_code=1)
        with mock.patch.dict(os.environ, env):
            hx.run_role("worker", "HX-T2", str(spec), reap=False)
        self.assertEqual(4, len(read_calls(fake_dir)))
        self.assertEqual(4, self.call_metrics(repo)[-1]["attempts"])

    def test_http_429_in_the_error_payload_retries(self):
        repo, p = self.new_task()
        spec = self.write_spec(repo)
        lines = [step_start(),
                 json.dumps({"type": "error", "timestamp": 1100, "sessionID": "ses_x",
                             "part": {"messageID": "m1", "message": "HTTP 429"}})]
        fake_dir, env = self.make_fake(lines, exit_code=1)
        with mock.patch.dict(os.environ, env):
            hx.run_role("worker", "HX-T2", str(spec), reap=False)
        self.assertEqual(4, len(read_calls(fake_dir)))
        self.assertEqual(4, self.call_metrics(repo)[-1]["attempts"])

    def test_timed_out_attempt_is_never_retried(self):
        repo, p = self.new_task()
        spec = self.write_spec(repo)
        _, env = self.make_fake([step_start()])
        timed_out = ("", "429 too many requests\nTIMEOUT", True, False)
        with mock.patch.dict(os.environ, env), mock.patch.object(hx, "run_streaming", return_value=timed_out) as rs:
            hx.run_role("worker", "HX-T2", str(spec), reap=False)
        self.assertEqual(1, rs.call_count)
        self.assertEqual([], sorted(p["state"].glob("worker-1.attempt*.jsonl")))

    def test_second_call_gets_the_next_number_not_an_attempt_file_number(self):
        repo, p = self.new_task()
        spec = self.write_spec(repo)
        fake_dir, env = self.make_fake([step_start()], exit_code=1, stderr="usage limit\n")
        with mock.patch.dict(os.environ, env):
            hx.run_role("worker", "HX-T2", str(spec), reap=False)
        fake_dir, env = self.make_fake([step_start(), text_event("bitti"), step_finish()])
        with mock.patch.dict(os.environ, env):
            hx.run_role("worker", "HX-T2", str(spec), reap=False)
        self.assertTrue((p["state"] / "worker-2.jsonl").exists())


class ErrorPayloadTest(unittest.TestCase):
    """Only the event's own envelope (type/ts/ids) is dropped; nested fields keep their values."""

    def test_top_level_envelope_metadata_is_not_searched(self):
        event = {"type": "error", "timestamp": 1795004290000, "sessionID": "ses_429",
                 "messageID": "msg_429",
                 "error": {"name": "APIError", "data": {"message": "model not found"}}}
        payload = hx.error_payload(event)
        self.assertNotIn("429", payload)
        self.assertFalse(hx.rate_limited(json.dumps(event), ""))

    def test_nested_error_type_survives_the_envelope_strip(self):
        event = {"type": "error", "timestamp": 1100,
                 "error": {"type": "rate_limit_error", "message": "slow down"}}
        self.assertIn("rate_limit_error", hx.error_payload(event))
        self.assertTrue(hx.rate_limited(json.dumps(event), ""))

    def test_nested_fields_survive_the_envelope_strip(self):
        event = {"type": "error", "timestamp": 1100, "sessionID": "ses_x", "messageID": "m1",
                 "error": {"type": "rate_limit_error", "message": "slow down",
                           "timestamp": 1100, "sessionID": "ses_inner", "messageID": "m_inner"}}
        stripped = hx.strip_meta(event)
        for key in ("type", "timestamp", "sessionID", "messageID"):
            self.assertNotIn(key, stripped)
        self.assertEqual(event["error"], stripped["error"])

    def test_nested_metadata_digits_do_not_fake_a_429_signal(self):
        event = {"type": "error", "timestamp": 1795004290000,
                 "error": {"type": "APIError", "message": "model not found",
                           "data": {"messageID": "msg_429", "timestamp": 1795004290000}}}
        payload = hx.error_payload(event)
        self.assertIn("msg_429", payload)
        self.assertFalse(hx.rate_limited(json.dumps(event), ""))

    def test_top_level_timestamp_whose_value_is_429_is_never_searched(self):
        event = {"type": "error", "timestamp": 429, "part": {"message": "model not found"}}
        self.assertEqual('{"part": {"message": "model not found"}}', hx.error_payload(event))
        self.assertFalse(hx.rate_limited(json.dumps(event), ""))

    def test_top_level_timestamp_containing_429_digits_is_never_searched(self):
        event = {"type": "error", "timestamp": 1795004290000, "part": {"message": "model not found"}}
        self.assertFalse(hx.rate_limited(json.dumps(event), ""))


class PairFailureTest(Base):
    def pair(self, **kwargs):
        repo, p = self.new_task()
        spec = self.write_spec(repo)
        fake_dir, env = self.make_fake([step_start(), text_event("worker bitti"), step_finish()])
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                hx.cmd_pair(NS(task="HX-T2", spec=str(spec), max_chars=2500))
            except SystemExit as e:
                code = e.code
        return repo, p, out.getvalue(), err.getvalue(), code

    def test_one_role_system_exit_keeps_the_other_roles_output(self):
        real = hx.run_role

        def failing(role, *args, **kwargs):
            if role == "tester":
                raise SystemExit("hx: unknown role tester")
            return real(role, *args, **kwargs)

        with mock.patch.object(hx, "run_role", side_effect=failing):
            repo, p, out, err, code = self.pair()
        self.assertEqual(2, code)
        self.assertIn("===== WORKER", out)
        self.assertNotIn("===== TESTER", out)
        self.assertTrue((p["state"] / "worker-1.jsonl").exists())
        self.assertIn("[hx] pair: tester failed: hx: unknown role tester", err)
        self.assertNotIn("Traceback", err)

    def test_integer_exit_code_is_reported_as_exit_code(self):
        real = hx.run_role

        def failing(role, *args, **kwargs):
            if role == "tester":
                raise SystemExit(1)
            return real(role, *args, **kwargs)

        with mock.patch.object(hx, "run_role", side_effect=failing):
            repo, p, out, err, code = self.pair()
        self.assertEqual(2, code)
        self.assertIn("[hx] pair: tester failed: exit code 1", err)
        self.assertNotIn("KeyError", err)
        self.assertNotIn("Traceback", err)
        self.assertIn("===== WORKER", out)

    def test_ordinary_exception_is_reported_without_a_keyerror(self):
        real = hx.run_role

        def failing(role, *args, **kwargs):
            if role == "tester":
                raise RuntimeError("boom")
            return real(role, *args, **kwargs)

        with mock.patch.object(hx, "run_role", side_effect=failing):
            repo, p, out, err, code = self.pair()
        self.assertEqual(2, code)
        self.assertIn("[hx] pair: tester failed: RuntimeError: boom", err)
        self.assertNotIn("KeyError", err)
        self.assertNotIn("Traceback", err)
        self.assertIn("===== WORKER", out)

    def test_both_roles_failing_reports_both_and_exits_two(self):
        def failing(role, *args, **kwargs):
            raise SystemExit(f"hx: {role} died")

        with mock.patch.object(hx, "run_role", side_effect=failing):
            repo, p, out, err, code = self.pair()
        self.assertEqual(2, code)
        self.assertIn("[hx] pair: tester failed: hx: tester died", err)
        self.assertIn("[hx] pair: worker failed: hx: worker died", err)
        self.assertEqual("", out)

    def test_both_succeed_unchanged(self):
        repo, p, out, err, code = self.pair()
        self.assertEqual(0, code)
        self.assertNotIn("[hx] pair:", err)
        self.assertIn("===== TESTER", out)
        self.assertIn("===== WORKER", out)
        self.assertEqual(2, len(self.call_metrics(repo)))


if __name__ == "__main__":
    unittest.main()
