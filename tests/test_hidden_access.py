"""HX-30 (b)+(c): hidden_access comes from resolved tool_use paths; a detected access fails the gate."""
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
from tests.helpers import fake_opencode, temp_repo

HID = "/r/.git/hx/T1/hidden"
STATE = "/r/.git/hx"
WT = "/r-wt/T1"


def tool_event(tool, **inp):
    return json.dumps({"type": "tool_use", "timestamp": 1000, "sessionID": "s",
                       "part": {"tool": tool, "state": {"input": inp}}})


def text_event(text):
    return json.dumps({"type": "text", "timestamp": 1100, "sessionID": "s", "part": {"messageID": "m", "text": text}})


def stream(*events):
    return "\n".join(events) + "\n"


def hits(*events, cwd=WT):
    return hx.hidden_accesses(stream(*events), cwd, [HID, STATE])


class DetectionTest(unittest.TestCase):
    # ---- canary-style accesses that must be caught
    def test_read_tool_on_the_hidden_dir(self):
        self.assertEqual([{"tool": "read", "path": f"{HID}/a.test.mjs"}], hits(tool_event("read", path=f"{HID}/a.test.mjs")))

    def test_shell_ls_cat_and_running_the_hidden_tests(self):
        self.assertTrue(hits(tool_event("shell", command=f"ls {HID} 2>/dev/null || true")))
        self.assertTrue(hits(tool_event("shell", command=f"node --test {HID}/*.test.mjs")))
        self.assertTrue(hits(tool_event("shell", command=f'cat "{HID}/a.py"')))

    def test_relative_paths_cd_and_dotdot(self):
        self.assertTrue(hits(tool_event("shell", command="cat ../../r/.git/hx/T1/hidden/a.py"), cwd="/r-wt/T1"))
        self.assertTrue(hits(tool_event("shell", command="cd /r/.git/hx && cat T1/hidden/a.py")))
        self.assertTrue(hits(tool_event("shell", command="cd /r/.git/hx/T1 && ls hidden")))

    def test_assignment_option_and_glob_forms(self):
        self.assertTrue(hits(tool_event("shell", command=f"HX_HIDDEN={HID} env")))
        self.assertTrue(hits(tool_event("shell", command=f"pytest --rootdir={HID}")))
        self.assertTrue(hits(tool_event("glob", pattern=f"{HID}/**/*.mjs")))
        self.assertTrue(hits(tool_event("grep", path=STATE, pattern="expected")))

    def test_state_dir_of_the_repo_counts(self):
        self.assertTrue(hits(tool_event("read", path="/r/.git/hx/metrics.jsonl")))

    def test_symlink_into_the_hidden_dir(self):
        with tempfile.TemporaryDirectory() as d:
            real = Path(d) / "state" / "hidden"
            real.mkdir(parents=True)
            link = Path(d) / "wt" / "link"
            link.parent.mkdir()
            os.symlink(real, link)
            got = hx.hidden_accesses(stream(tool_event("read", path=str(link / "a.py"))), str(link.parent),
                                     [str(real), str(Path(d) / "state")])
            self.assertEqual(1, len(got))

    # ---- things that must NOT be flagged (the old substring test flagged them)
    def test_text_and_tool_output_mentions_are_not_accesses(self):
        raw = stream(text_event(f"I will not look at {HID}"),
                     json.dumps({"type": "tool_use", "part": {"tool": "shell", "state": {
                         "input": {"command": "ps -Ao command | head"}, "output": f"node {HID}/a.test.mjs"}}}))
        self.assertEqual([], hx.hidden_accesses(raw, WT, [HID, STATE]))

    def test_other_repos_hx_dirs_and_the_repo_git_dir_are_not_hidden(self):
        self.assertEqual([], hits(tool_event("shell", command="cd /tmp/e2e && git init && ls .git/hx"), cwd="/tmp/e2e"))
        self.assertEqual([], hits(tool_event("shell", command="ls /r/.git && cat /r/.git/config")))
        self.assertEqual([], hits(tool_event("read", path="/r/.git/hx2/x")))
        self.assertEqual([], hits(tool_event("read", path="/other/.git/hx/T1/hidden/a.py")))

    def test_patterns_and_source_text_that_name_the_directory_are_not_paths(self):
        self.assertEqual([], hits(tool_event("shell", command='grep -rn "/.git/hx/" src | head')))
        self.assertEqual([], hits(tool_event("edit", path=f"{WT}/hx.py", oldString=f"x = '{HID}'", newString="y")))
        self.assertEqual([], hits(tool_event("write", path=f"{WT}/n.py", content=f"print('{HID}')")))
        self.assertEqual([], hits(tool_event("shell", command="grep hidden README.md")))

    def test_worktree_and_bad_input_are_fine(self):
        self.assertEqual([], hits(tool_event("read", path=f"{WT}/src/a.py"), tool_event("shell", command="echo 'unterminated")))
        self.assertEqual([], hx.hidden_accesses("not json\n{broken", WT, [HID]))


class Base(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(hx.time, "sleep", lambda *_: None))
        self.repo = self.stack.enter_context(temp_repo())
        with contextlib.redirect_stdout(io.StringIO()):
            hx.cmd_new(NS(task="HX-H1", base=None, branch=None, setup=None))
        self.p = hx.task_paths("HX-H1")
        self.spec = Path(self.repo).parent / "spec.md"
        self.spec.write_text("# G\nx\n\n## Kapsam\nhx.py\n", encoding="utf-8")

    def run_role(self, role, events):
        d = tempfile.mkdtemp(prefix="hx-fake-")
        self.addCleanup(shutil.rmtree, d, True)
        env = fake_opencode(d, events)
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()):
            return hx.run_role(role, "HX-H1", str(self.spec), reap=False)

    def call_records(self):
        text = (hx.state_dir() / "metrics.jsonl").read_text()
        return [json.loads(l) for l in text.splitlines() if json.loads(l).get("event") == "call"]

    def gate(self):
        args = NS(task="HX-H1", test='python3 -c "pass"', hidden_cmd=None, allow="**", protect=None, retry=0,
                  gate_timeout=60, no_tests=False)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as cm:
            hx.cmd_gate(args)
        payload = next(json.loads(l) for l in buf.getvalue().splitlines() if l.startswith("{"))
        return cm.exception.code, payload


class NS:
    def __init__(self, **kw):
        self.__dict__.update(kw)


STEP = json.dumps({"type": "step_finish", "timestamp": 1500, "sessionID": "s", "part": {"tokens": {"input": 1, "output": 1}}})


class CanaryTest(Base):
    def test_canary_worker_reading_the_hidden_dir_is_recorded_and_fails_the_gate(self):
        self.run_role("worker", [tool_event("shell", command=f"cat {self.p['hidden']}/secret.test.py"), STEP])
        rec = self.call_records()[-1]
        self.assertTrue(rec["hidden_access"])
        self.assertEqual(str(self.p["hidden"]) + "/secret.test.py", rec["hidden_paths"][0]["path"])
        self.assertTrue((self.p["state"] / "hidden_access.json").exists())
        code, payload = self.gate()
        self.assertEqual(1, code)
        self.assertEqual("FAIL", payload["gate"])
        self.assertIn(str(self.p["hidden"]) + "/secret.test.py", payload["hidden_access"])
        self.assertIn("hidden_access", (self.p["state"] / "last_gate.txt").read_text())

    def test_fresh_tester_suite_clears_the_flag(self):
        self.run_role("worker", [tool_event("read", path=f"{self.p['hidden']}/x.py"), STEP])
        self.assertEqual(1, self.gate()[0])
        self.run_role("tester", [tool_event("write", path=f"{self.p['hidden']}/new.test.py", content="x"), STEP])
        self.assertFalse((self.p["state"] / "hidden_access.json").exists())
        code, payload = self.gate()
        self.assertEqual(0, code)
        self.assertNotIn("hidden_access", payload)

    def test_innocent_worker_mentioning_the_path_is_not_flagged(self):
        self.run_role("worker", [text_event(f"never read {self.p['hidden']}"),
                                 tool_event("shell", command="grep -rn '/.git/hx/' . | head"), STEP])
        self.assertFalse(self.call_records()[-1]["hidden_access"])
        self.assertFalse((self.p["state"] / "hidden_access.json").exists())
        self.assertEqual(0, self.gate()[0])

    def test_tester_and_judge_reading_hidden_is_never_flagged(self):
        self.run_role("tester", [tool_event("read", path=f"{self.p['hidden']}/x.py"), STEP])
        self.assertFalse(self.call_records()[-1]["hidden_access"])


class IsolationAgentTest(Base):
    """HX-30 (a)/(d): opt-in per-role OpenCode agent that fences the hidden dir (rules verified on OpenCode v2.3.0
    with real canary runs; recorded in the notes)."""

    def perms(self, kind):
        name, cfg = hx.isolation_agent(kind, self.p["hidden"], hx.state_dir())
        self.assertEqual(f"hx-{kind}", name)
        return cfg["agents"][name]["permissions"]

    def test_worker_agent_denies_external_directory_and_read_for_hidden_and_state(self):
        perms = self.perms("worker")
        self.assertEqual({"action": "*", "resource": "*", "effect": "allow"}, perms[0])  # broad rule first
        for action in ("external_directory", "read"):
            for root in (str(self.p["hidden"]), str(hx.state_dir())):
                for suffix in ("", "/*", "/**"):
                    self.assertIn({"action": action, "resource": os.path.realpath(root) + suffix, "effect": "deny"}, perms)
        self.assertTrue(all(r["effect"] == "deny" for r in perms[1:]))  # last match wins: no allow after the denies

    def test_tester_agent_allows_edits_only_inside_the_hidden_dir(self):
        perms = self.perms("tester")
        self.assertEqual({"action": "edit", "resource": "*", "effect": "deny"}, perms[1])
        allowed = [r["resource"] for r in perms[2:]]
        self.assertTrue(allowed and all(r["effect"] == "allow" and r["action"] == "edit" for r in perms[2:]))
        self.assertTrue(all(x.startswith((str(self.p["hidden"]), os.path.realpath(str(self.p["hidden"])))) for x in allowed))
        self.assertFalse(any("/.git/hx/" in x and not x.startswith(str(self.p["hidden"])) and "hidden" not in x for x in allowed))

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            hx.isolation_agent("nope", "/h", "/s")

    def run_with_capture(self, role, **role_cfg):
        seen = {}

        def fake_streaming(args, cwd, env, limit, stall_limit):
            seen["args"], seen["env"] = args, env
            return STEP + "\n", "", False, False
        cfg = dict(hx.CFG["roles"][role], **role_cfg)
        with mock.patch.dict(hx.CFG["roles"], {role: cfg}), mock.patch.object(hx, "run_streaming", fake_streaming), \
                contextlib.redirect_stdout(io.StringIO()):
            hx.run_role(role, "HX-H1", str(self.spec), reap=False)
        return seen

    def test_isolation_is_off_by_default(self):
        seen = self.run_with_capture("worker")
        self.assertNotIn("--standalone", seen["args"])
        self.assertNotIn("--agent", seen["args"])
        self.assertNotIn("OPENCODE_CONFIG_CONTENT", seen["env"])

    def test_worker_isolation_adds_agent_standalone_and_config(self):
        seen = self.run_with_capture("worker", isolation="worker")
        args = seen["args"]
        self.assertIn("--standalone", args)
        self.assertEqual("hx-worker", args[args.index("--agent") + 1])
        cfg = json.loads(seen["env"]["OPENCODE_CONFIG_CONTENT"])
        self.assertIn("hx-worker", cfg["agents"])

    def test_existing_config_content_is_merged_not_replaced(self):
        with mock.patch.dict(os.environ, {"OPENCODE_CONFIG_CONTENT": json.dumps({"theme": "x", "agents": {"keep": {}}})}):
            seen = self.run_with_capture("worker", isolation="worker")
        cfg = json.loads(seen["env"]["OPENCODE_CONFIG_CONTENT"])
        self.assertEqual("x", cfg["theme"])
        self.assertEqual({"keep", "hx-worker"}, set(cfg["agents"]))

    def test_read_only_roles_keep_the_plan_agent(self):
        seen = self.run_with_capture("judge", isolation="worker")
        args = seen["args"]
        self.assertEqual("plan", args[args.index("--agent") + 1])
        self.assertNotIn("--standalone", args)


if __name__ == "__main__":
    unittest.main()
