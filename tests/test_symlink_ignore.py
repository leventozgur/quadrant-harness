"""HX-37: a symlink to a directory is as ignored as the directory when a `name/` rule covers it."""
import contextlib
import io
import os
import subprocess
import unittest

import hx
from tests.helpers import temp_repo
from tests.test_gate import NS, run_gate


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True).stdout


class SymlinkIgnoreTest(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.repo = self.stack.enter_context(temp_repo())
        with contextlib.redirect_stdout(io.StringIO()):
            hx.cmd_new(NS(task="HX-G1", base=None, branch=None, setup=None))
        self.wt = hx.task_paths("HX-G1")["worktree"]
        self.target = self.repo.parent / "shared-modules"
        self.target.mkdir()
        (self.target / "pkg.js").write_text("x\n")

    def commit_ignore(self, text, where=""):
        d = self.wt / where
        d.mkdir(parents=True, exist_ok=True)
        (d / ".gitignore").write_text(text)
        git(self.wt, "add", "-A")
        git(self.wt, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "ignore")
        return git(self.wt, "rev-parse", "HEAD").strip()

    def changed(self, base):
        return hx.changed_files(self.wt, base)

    def test_symlinked_dir_covered_by_a_dir_rule_is_not_changed(self):
        base = self.commit_ignore("node_modules/\n")
        os.symlink(self.target, self.wt / "node_modules")
        self.assertEqual([], self.changed(base))

    def test_anchored_and_glob_rules(self):
        base = self.commit_ignore("/node_modules/\n.cache-*/\n")
        os.symlink(self.target, self.wt / "node_modules")
        os.symlink(self.target, self.wt / ".cache-abc")
        self.assertEqual([], self.changed(base))

    def test_uncovered_symlink_is_still_reported(self):
        base = self.commit_ignore("node_modules/\n")
        os.symlink(self.target, self.wt / "other_link")
        self.assertEqual(["other_link"], self.changed(base))

    def test_negation_after_the_rule_unignores(self):
        base = self.commit_ignore("node_modules/\n!node_modules/\n")
        os.symlink(self.target, self.wt / "node_modules")
        self.assertEqual(["node_modules"], self.changed(base))

    def test_nested_gitignore_applies_to_its_subtree_only(self):
        base = self.commit_ignore("node_modules/\n", where="pkg")
        os.symlink(self.target, self.wt / "pkg" / "node_modules")
        os.symlink(self.target, self.wt / "node_modules")
        self.assertEqual(["node_modules"], self.changed(base))

    def test_symlink_to_a_file_or_dangling_is_not_treated_as_a_directory(self):
        base = self.commit_ignore("node_modules/\n")
        os.symlink(self.target / "pkg.js", self.wt / "node_modules")
        os.symlink(self.repo.parent / "missing", self.wt / "dangling")
        self.assertEqual(["dangling", "node_modules"], self.changed(base))

    def test_real_ignored_directory_still_works(self):
        base = self.commit_ignore("node_modules/\n")
        (self.wt / "node_modules").mkdir()
        (self.wt / "node_modules" / "a.js").write_text("x\n")
        self.assertEqual([], self.changed(base))

    def test_gate_has_no_out_of_scope_for_the_ignored_symlink(self):
        self.commit_ignore("node_modules/\n")
        meta = hx.task_paths("HX-G1")["meta"]
        import json
        data = json.loads(meta.read_text())
        data["base"] = git(self.wt, "rev-parse", "HEAD").strip()
        meta.write_text(json.dumps(data))
        os.symlink(self.target, self.wt / "node_modules")
        (self.wt / "impl.py").write_text("x\n")
        code, payload, _ = run_gate(test='python3 -c "pass"', allow="impl.py")
        self.assertEqual(0, code)
        self.assertEqual(["impl.py"], payload["changed"])
        self.assertEqual([], payload["out_of_scope"])

    def prepare_task_with_symlink(self):
        p = hx.task_paths("HX-G1")
        self.commit_ignore("node_modules/\n")
        import json
        data = json.loads(p["meta"].read_text())
        data["base"] = git(self.wt, "rev-parse", "HEAD").strip()
        p["meta"].write_text(json.dumps(data))
        os.symlink(self.target, self.wt / "node_modules")
        (self.wt / "impl.py").write_text("x\n")
        return p, data["base"]

    def test_intent_to_add_symlink_from_an_older_worktree_is_still_ignored(self):
        p, base = self.prepare_task_with_symlink()
        git(self.wt, "add", "-N", ".")  # what an older hx did: the symlink is now an intent-to-add index entry
        self.assertIn("node_modules", git(self.wt, "diff", "--name-only"))
        self.assertEqual(["impl.py"], hx.changed_files(self.wt, base))
        code, payload, _ = run_gate(test='python3 -c "pass"', allow="impl.py")
        self.assertEqual(0, code)
        self.assertEqual([], payload["out_of_scope"])

    def test_end_to_end_diff_review_commit_with_a_symlinked_worktree(self):
        """hx diff -> hx review ONAY -> hx commit must pass in a worktree holding the ignored symlink, both with a
        fresh symlink and with one an older hx left as intent-to-add."""
        for ita in (False, True):
            with self.subTest(intent_to_add=ita):
                p, base = self.prepare_task_with_symlink() if not (self.wt / "node_modules").is_symlink() \
                    else (hx.task_paths("HX-G1"), None)
                if ita:
                    git(self.wt, "add", "-N", ".")
                code, _, _ = run_gate(test='python3 -c "pass"', allow="**")
                self.assertEqual(0, code)
                with contextlib.redirect_stdout(io.StringIO()):
                    hx.cmd_diff(NS(task="HX-G1", all=False))
                diff = (p["state"] / "review.diff").read_text()
                self.assertNotIn("node_modules", diff)
                out = p["state"] / "reviewer_output.md"
                out.write_text("ONAY\n")
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(SystemExit) as cm:
                        hx.cmd_review(NS(task="HX-G1", output=str(out)))
                self.assertEqual(0, cm.exception.code)
                with contextlib.redirect_stdout(io.StringIO()):
                    hx.cmd_commit(NS(task="HX-G1", m=f"phase {ita}", review=None, phase="1", next=None))
                files = git(self.wt, "show", "--name-only", "--format=", "HEAD").split()
                self.assertNotIn("node_modules", files)
                self.assertTrue(os.path.islink(self.wt / "node_modules"))
                (self.wt / f"next{ita}.py").write_text("y\n")  # change for the second round


if __name__ == "__main__":
    unittest.main()
