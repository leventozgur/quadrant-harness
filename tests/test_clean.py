"""HX-36: hx clean removes a task's worktree (and optionally branch) and refuses to drop unsaved work silently."""
import contextlib
import io
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import hx
from tests.helpers import temp_repo


class NS:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True).stdout


def branches(repo):
    return git(repo, "branch", "--format=%(refname:short)").split()


class CleanTest(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.repo = self.stack.enter_context(temp_repo())
        with contextlib.redirect_stdout(io.StringIO()):
            hx.cmd_new(NS(task="HX-C1", base=None, branch=None, setup=None))
        self.p = hx.task_paths("HX-C1")
        self.wt = self.p["worktree"]

    def clean(self, **kw):
        args = dict(task="HX-C1", branch=False, yes=False, dry_run=False)
        args.update(kw)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                hx.cmd_clean(NS(**args))
                code = None
            except SystemExit as e:
                code = e.code
        return code, buf.getvalue()

    def commit_in_worktree(self, name="f.txt"):
        (self.wt / name).write_text("x\n")
        git(self.wt, "add", name)
        git(self.wt, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", f"add {name}")

    def test_clean_worktree_is_removed_branch_and_state_stay(self):
        code, out = self.clean()
        self.assertIsNone(code, out)
        self.assertFalse(self.wt.exists())
        self.assertNotIn(str(self.wt), git(self.repo, "worktree", "list"))
        self.assertIn("hx/HX-C1", branches(self.repo))
        self.assertTrue((self.p["state"] / "task.json").exists())
        self.assertTrue(self.p["hidden"].exists())

    def test_branch_flag_deletes_a_merged_branch(self):
        code, _ = self.clean(branch=True)
        self.assertIsNone(code)
        self.assertNotIn("hx/HX-C1", branches(self.repo))

    def test_dry_run_changes_nothing(self):
        (self.wt / "dirty.txt").write_text("x")
        code, out = self.clean(dry_run=True, branch=True)
        self.assertIsNone(code)
        self.assertIn("dry run", out)
        self.assertIn("uncommitted", out)
        self.assertTrue(self.wt.exists())
        self.assertIn("hx/HX-C1", branches(self.repo))

    def test_uncommitted_work_needs_confirmation(self):
        (self.wt / "dirty.txt").write_text("x")
        with mock.patch.object(hx.sys.stdin, "isatty", return_value=False):
            code, out = self.clean()
        self.assertIn("--yes", str(code))
        self.assertIn("uncommitted change", out)
        self.assertTrue(self.wt.exists())
        code, _ = self.clean(yes=True)
        self.assertIsNone(code)
        self.assertFalse(self.wt.exists())

    def test_unmerged_commits_block_branch_deletion_until_yes(self):
        self.commit_in_worktree()
        with mock.patch.object(hx.sys.stdin, "isatty", return_value=False):
            code, out = self.clean(branch=True)
        self.assertIn("--yes", str(code))
        self.assertIn("1 commit(s) on hx/HX-C1 not on", out)
        self.assertTrue(self.wt.exists())
        self.assertIn("hx/HX-C1", branches(self.repo))
        code, _ = self.clean(branch=True, yes=True)
        self.assertIsNone(code)
        self.assertFalse(self.wt.exists())
        self.assertNotIn("hx/HX-C1", branches(self.repo))

    def test_interactive_answer_decides(self):
        (self.wt / "dirty.txt").write_text("x")
        with mock.patch.object(hx.sys.stdin, "isatty", return_value=True), \
                mock.patch("builtins.input", return_value="n"):
            code, _ = self.clean()
        self.assertIn("cancelled", str(code))
        self.assertTrue(self.wt.exists())
        with mock.patch.object(hx.sys.stdin, "isatty", return_value=True), \
                mock.patch("builtins.input", return_value="y"):
            code, _ = self.clean()
        self.assertIsNone(code)
        self.assertFalse(self.wt.exists())

    def test_refuses_from_inside_the_worktree(self):
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.wt)
        code, _ = self.clean()
        self.assertIn("inside the worktree", str(code))
        self.assertTrue(self.wt.exists())

    def test_unknown_task_and_main_worktree_are_refused(self):
        code, _ = self.clean(task="NOPE")
        self.assertIn("nothing to clean", str(code))
        meta = self.p["state"] / "task.json"
        import json
        data = json.loads(meta.read_text())
        data["worktree"] = str(self.repo)
        meta.write_text(json.dumps(data))
        code, _ = self.clean(yes=True)
        self.assertIn("main worktree", str(code))
        self.assertTrue((self.repo / "README.md").exists())

    def test_already_deleted_worktree_directory_is_pruned(self):
        import shutil
        shutil.rmtree(self.wt)
        code, _ = self.clean(branch=True)
        self.assertIsNone(code)
        self.assertNotIn(str(self.wt), git(self.repo, "worktree", "list"))
        self.assertNotIn("hx/HX-C1", branches(self.repo))

    def test_clean_is_recorded_in_metrics(self):
        self.clean()
        text = (hx.state_dir() / "metrics.jsonl").read_text()
        self.assertIn('"event": "clean"', text)


if __name__ == "__main__":
    unittest.main()
