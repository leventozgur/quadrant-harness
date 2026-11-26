"""HX-FIX13: sandbox enabled per project through the top-level `sandbox_repos` list."""
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
from tests.helpers import temp_repo

STEP = json.dumps({"type": "step_finish", "timestamp": 1500, "sessionID": "s", "part": {"tokens": {"input": 1, "output": 1}}})


class NS:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class MatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hx-match-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.checkout = Path(self.tmp) / "Mizan"
        (self.checkout / ".git").mkdir(parents=True)

    def test_dot_git_common_dir_uses_its_parent_and_exact_name(self):
        common = self.checkout / ".git"
        self.assertTrue(hx.sandbox_repo_match(common, ["Mizan"]))
        self.assertFalse(hx.sandbox_repo_match(common, ["mizan"]))
        self.assertFalse(hx.sandbox_repo_match(common, ["Mizan2"]))

    def test_an_absolute_path_is_compared_by_realpath(self):
        common = self.checkout / ".git"
        self.assertTrue(hx.sandbox_repo_match(common, [str(self.checkout)]))
        self.assertFalse(hx.sandbox_repo_match(common, [str(Path(self.tmp) / "Other")]))

    def test_a_non_dot_git_common_dir_is_the_bare_checkout(self):
        bare = Path(self.tmp) / "bare.git"
        bare.mkdir()
        self.assertTrue(hx.sandbox_repo_match(bare, ["bare.git"]))
        self.assertTrue(hx.sandbox_repo_match(bare, [str(bare)]))
        self.assertFalse(hx.sandbox_repo_match(bare, ["bare"]))

    def test_empty_or_missing_names_never_match(self):
        common = self.checkout / ".git"
        self.assertFalse(hx.sandbox_repo_match(common, []))
        self.assertFalse(hx.sandbox_repo_match(common, None))


class Base(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(hx.time, "sleep", lambda *_: None))
        self.repo = self.stack.enter_context(temp_repo())
        with contextlib.redirect_stdout(io.StringIO()):
            hx.cmd_new(NS(task="HX-R1", base=None, branch=None, setup=None))
        self.p = hx.task_paths("HX-R1")
        self.spec = Path(self.repo).parent / "spec.md"
        self.spec.write_text("# G\nx\n\n## Kapsam\nhx.py\n", encoding="utf-8")

    def run_captured(self, role, role_cfg=None, sandbox_repos=(), **kwargs):
        seen = {}

        def fake_streaming(args, cwd, env, limit, stall_limit):
            seen["args"] = args
            return STEP + "\n", "", False, False

        cfg = dict(hx.CFG["roles"][role], **(role_cfg or {}))
        patches = [mock.patch.dict(hx.CFG["roles"], {role: cfg}),
                   mock.patch.object(hx, "run_streaming", fake_streaming),
                   mock.patch.object(hx, "sandbox_self_check", lambda *_: None),
                   mock.patch.object(hx.sys, "platform", "darwin"),
                   mock.patch.object(hx.shutil, "which", lambda *_: "/usr/bin/sandbox-exec"),
                   mock.patch.dict(hx.CFG, {"sandbox_repos": list(sandbox_repos)})]
        with contextlib.ExitStack() as st:
            for p in patches:
                st.enter_context(p)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(seen.setdefault("stderr", io.StringIO())):
                hx.run_role(role, "HX-R1", str(self.spec), reap=False, **kwargs)
        return seen

    def call_record(self):
        text = (hx.state_dir() / "metrics.jsonl").read_text()
        return [json.loads(l) for l in text.splitlines() if json.loads(l).get("event") == "call"][-1]


class RepoMatchTest(Base):
    def test_a_matching_repo_sandboxes_silently_and_records_the_reason(self):
        seen = self.run_captured("worker", sandbox_repos=["repo"])
        self.assertEqual(["sandbox-exec", "-f", str(self.p["state"] / "sandbox-worker-1.sb"),
                          "opencode", "run", "--standalone"], seen["args"][:6])
        self.assertEqual("", seen["stderr"].getvalue())
        rec = self.call_record()
        self.assertTrue(rec["sandbox"])
        self.assertEqual("repo", rec["sandbox_reason"])

    def test_an_absolute_path_in_the_list_matches_too(self):
        seen = self.run_captured("worker", sandbox_repos=[os.path.realpath(str(self.repo))])
        self.assertIn("sandbox-exec", seen["args"])
        self.assertEqual("repo", self.call_record()["sandbox_reason"])

    def test_escalate_is_sandboxed_too(self):
        seen = self.run_captured("escalate", sandbox_repos=["repo"])
        self.assertIn("sandbox-exec", seen["args"])
        self.assertEqual("repo", self.call_record()["sandbox_reason"])

    def test_a_repo_outside_the_list_is_not_sandboxed(self):
        seen = self.run_captured("worker", sandbox_repos=["Mizan"])
        self.assertNotIn("sandbox-exec", seen["args"])
        rec = self.call_record()
        self.assertNotIn("sandbox", rec)
        self.assertNotIn("sandbox_reason", rec)
        self.assertEqual("", seen["stderr"].getvalue())

    def test_hidden_role_repo_match_is_ignored_silently(self):
        seen = self.run_captured("tester", sandbox_repos=["repo"])
        self.assertNotIn("sandbox-exec", seen["args"])
        self.assertEqual("", seen["stderr"].getvalue())
        self.assertNotIn("sandbox", self.call_record())

    def test_read_only_repo_match_is_ignored_silently(self):
        seen = self.run_captured("worker", sandbox_repos=["repo"], read_only=True)
        self.assertNotIn("sandbox-exec", seen["args"])
        self.assertEqual("", seen["stderr"].getvalue())
        self.assertNotIn("sandbox", self.call_record())


class RoleFlagTest(Base):
    def test_the_role_flag_wins_over_a_repo_match(self):
        seen = self.run_captured("worker", {"sandbox": True}, sandbox_repos=["repo"])
        self.assertIn("sandbox-exec", seen["args"])
        self.assertEqual("role", self.call_record()["sandbox_reason"])

    def test_the_role_flag_still_warns_on_a_hidden_role(self):
        seen = self.run_captured("tester", {"sandbox": True}, sandbox_repos=["repo"])
        self.assertEqual("hx: sandbox ignored for role tester\n", seen["stderr"].getvalue())
        self.assertNotIn("sandbox-exec", seen["args"])
        self.assertNotIn("sandbox", self.call_record())


class ConfigTest(unittest.TestCase):
    def test_the_shipped_list_contains_the_two_projects_only(self):
        self.assertEqual(["Mizan", "BrainAtlas"], hx.CFG.get("sandbox_repos"))
        self.assertNotIn("quadrant-harness", hx.CFG["sandbox_repos"])


if __name__ == "__main__":
    unittest.main()
