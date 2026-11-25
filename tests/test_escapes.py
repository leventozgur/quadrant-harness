"""Tests for lab/escapes/corpus.py.

Everything runs against throwaway git repositories and a fake `ESCAPES_OPENCODE`
script: the real `opencode` is never started and no network is used.
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CORPUS = Path(__file__).resolve().parent.parent / "lab" / "escapes" / "corpus.py"
sys.path.insert(0, str(CORPUS.parent))

import corpus  # noqa: E402

BASE_CALC = "def double(n):\n    return n * 2\n"
FEAT_CALC = "def double(n):\n    return n * 2\n\n\ndef triple(n):\n    return n * 3\n"
DEFECT_CALC = FEAT_CALC.replace("n * 3", "n + 3")
SPEC = "# Görev\ntriple ekle\n\n## Kapsam\nsrc/calc.py\n"
TEST_CMD = "python3 -c \"import sys; sys.path.insert(0, '.'); from src.calc import double; assert double(2) == 4\""
HIDDEN_CMD = "python3 -c \"import sys; sys.path.insert(0, '.'); from src.calc import triple; assert triple(3) == 9\""

# The fake model: records argv/cwd, applies the edit planned for this call, optionally
# commits it, prints one opencode-format text event (so lab/run_oc.py's parse() finds the answer).
FAKE = """#!/usr/bin/env python3
import json, os, subprocess, sys
here = os.path.dirname(os.path.abspath(__file__))
log = os.path.join(here, "calls.jsonl")
calls = []
if os.path.exists(log):
    calls = [line for line in open(log, encoding="utf-8") if line.strip()]
with open(log, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\\n")
with open(os.path.join(here, "cwds.jsonl"), "a", encoding="utf-8") as handle:
    handle.write(json.dumps(os.getcwd()) + "\\n")
with open(os.path.join(here, "pwds.jsonl"), "a", encoding="utf-8") as handle:
    handle.write(json.dumps(os.environ.get("PWD")) + "\\n")
plan = json.load(open(os.path.join(here, "action.json"), encoding="utf-8"))
for path, content in (plan.get("foreign") or {}).items():
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
edits = plan.get("edits") or []
step = edits[len(calls)] if len(calls) < len(edits) else {}
for name, content in (step or {}).items():
    path = os.path.join(os.getcwd(), name)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
if plan.get("commit"):
    subprocess.run(["git", "add", "-A"], cwd=os.getcwd(), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "model commit"], cwd=os.getcwd(), check=True)
answers = plan.get("answers") or []
text = answers[len(calls)] if len(calls) < len(answers) else ""
sys.stdout.write(json.dumps({"type": "text", "part": {"messageID": "m1", "text": text}},
                            ensure_ascii=False) + "\\n")
"""

# A stand-in for /usr/bin/sandbox-exec: records its argv and runs the wrapped command.
SANDBOX_SHIM = """#!/bin/sh
printf '%s\\n' "$*" >> "$(dirname "$0")/calls.txt"
shift 2
exec "$@"
"""


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def make_repo(root, before, after, name="repo"):
    repo = Path(root) / name
    repo.mkdir()
    git(repo, "init", "-q")
    for key, value in (("user.name", "corpus tests"), ("user.email", "corpus@example.invalid"),
                       ("commit.gpgsign", "false"), ("tag.gpgsign", "false")):
        git(repo, "config", key, value)
    for relative, text in before.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            path.write_bytes(text)
        else:
            path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    for relative, text in after.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            path.write_bytes(text)
        else:
            path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "feature")
    return repo, git(repo, "rev-parse", "HEAD^").strip(), git(repo, "rev-parse", "HEAD").strip()


def fake(root, name="fake", edits=None, answers=None, commit=False, foreign=None):
    directory = Path(root) / name
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "opencode"
    script.write_text(FAKE, encoding="utf-8")
    script.chmod(0o755)
    plan = {"edits": edits or [], "answers": answers or [], "commit": bool(commit),
            "foreign": foreign or {}}
    (directory / "action.json").write_text(json.dumps(plan), encoding="utf-8")
    (directory / "calls.jsonl").write_text("", encoding="utf-8")
    (directory / "cwds.jsonl").write_text("", encoding="utf-8")
    (directory / "pwds.jsonl").write_text("", encoding="utf-8")
    return script, directory


def calls(directory):
    text = (Path(directory) / "calls.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def cwds(directory):
    text = (Path(directory) / "cwds.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def pwds(directory):
    text = (Path(directory) / "pwds.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def cli(*args, opencode=None, expect_ok=True, path_prefix=None):
    env = dict(os.environ)
    if opencode is not None:
        env["ESCAPES_OPENCODE"] = str(opencode)
    if path_prefix is not None:
        env["PATH"] = str(path_prefix) + os.pathsep + env.get("PATH", "")
    proc = subprocess.run([sys.executable, "-I", str(CORPUS), *[str(arg) for arg in args]],
                          capture_output=True, text=True, env=env)
    if expect_ok and proc.returncode != 0:
        raise AssertionError(f"corpus {args} failed ({proc.returncode}): {proc.stdout}\n{proc.stderr}")
    return proc


def case_entry(repo, spec, hidden, commit, case_id="c1", **overrides):
    entry = {"id": case_id, "repo": str(repo), "task": case_id, "spec": str(spec),
             "commit": commit, "hidden_dir": str(hidden), "setup": "",
             "test_cmd": TEST_CMD, "hidden_cmd": HIDDEN_CMD}
    entry.update(overrides)
    return entry


class CorpusTestCase(unittest.TestCase):
    """Shared fixture: a feature commit on top of a base commit, plus a spec and hidden dir."""

    before = {"src/calc.py": BASE_CALC, "src/other.py": "def one():\n    return 1\n"}
    after = {"src/calc.py": FEAT_CALC}

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="corpus-tests-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo, self.base, self.commit = make_repo(self.tmp, self.before, self.after)
        self.spec = Path(self.tmp) / "spec.md"
        self.spec.write_text(SPEC, encoding="utf-8")
        self.hidden = Path(self.tmp) / "hidden"
        self.hidden.mkdir()
        (self.hidden / "check.py").write_text("ok\n", encoding="utf-8")
        self.out = Path(self.tmp) / "out"
        self.sandbox_bin = Path(self.tmp) / "sandbox-bin"
        self.sandbox_bin.mkdir()
        shim = self.sandbox_bin / "sandbox-exec"
        shim.write_text(SANDBOX_SHIM, encoding="utf-8")
        shim.chmod(0o755)

    def entry(self, case_id="c1", **overrides):
        return case_entry(self.repo, self.spec, self.hidden, self.commit, case_id, **overrides)

    def build(self, entries=None, **overrides):
        entries = entries if entries is not None else [self.entry(**overrides)]
        path = Path(self.tmp) / "manifest.json"
        path.write_text(json.dumps(entries), encoding="utf-8")
        return cli("build", path, self.out)

    def load(self, case_id="c1"):
        return json.loads((self.out / "cases" / f"{case_id}.json").read_text(encoding="utf-8"))

    def mutate(self, script, *extra, case_id="c1"):
        return cli("mutate", self.out, *extra, opencode=script, path_prefix=self.sandbox_bin)

    def mutate_normally(self, edits=None, answers=None, name="mut", attempts=2):
        edits = edits if edits is not None else [{"src/calc.py": DEFECT_CALC}]
        answers = answers if answers is not None else ['{"file": "src/calc.py", "answer_key": "triple n+3 döndürüyor"}']
        script, directory = fake(self.tmp, name, edits=edits * attempts, answers=answers * attempts)
        self.mutate(script)
        return script, directory


class BuildTest(CorpusTestCase):
    def test_build_writes_the_case_worktrees_and_the_correct_diff(self):
        proc = self.build()
        case = self.load()
        self.assertEqual("built", case["status"])
        self.assertEqual(self.base, case["base"])
        self.assertEqual(["src/calc.py"], case["ref_files"])
        self.assertEqual("EDGE", case["class"])
        self.assertEqual(self.commit, git(self.out / "wt" / "c1__clean", "rev-parse", "HEAD").strip())
        self.assertTrue((self.out / "wt" / "c1__defect").is_dir())
        diff = (self.out / "diffs" / "c1__clean.diff").read_text(encoding="utf-8")
        self.assertIn("+def triple(n):", diff)
        self.assertEqual(1, len(proc.stdout.strip().splitlines()))
        self.assertIn("build: 1 built", proc.stdout)

    def test_class_follows_the_index_in_the_id_sorted_manifest(self):
        self.build([self.entry("b"), self.entry("a")])
        self.assertEqual("EDGE", self.load("a")["class"])
        self.assertEqual("SWALLOW", self.load("b")["class"])

    def test_existing_case_is_skipped_on_a_second_build(self):
        self.build()
        before = (self.out / "cases" / "c1.json").read_text(encoding="utf-8")
        proc = self.build()
        self.assertIn("0 built, 1 skipped", proc.stdout)
        self.assertEqual(before, (self.out / "cases" / "c1.json").read_text(encoding="utf-8"))

    def test_the_repo_path_is_kept_as_given(self):
        self.build()
        self.assertEqual(str(self.repo), self.load()["repo"])

    def test_build_survives_non_utf8_bytes_in_the_diff(self):
        repo, base, commit = make_repo(self.tmp, {"bin.dat": b"a\n"}, {"bin.dat": b"a\xff\n"}, name="repo-bin")
        self.build([case_entry(repo, self.spec, self.hidden, commit)])
        case = self.load()
        self.assertEqual("built", case["status"])
        self.assertEqual(["bin.dat"], case["ref_files"])
        self.assertTrue((self.out / "diffs" / "c1__clean.diff").read_text(encoding="utf-8"))


class MutateTest(CorpusTestCase):
    def test_a_small_in_scope_defect_is_accepted(self):
        self.build()
        _, directory = self.mutate_normally()
        case = self.load()
        self.assertEqual("mutated", case["status"])
        self.assertEqual("src/calc.py", case["defect_file"])
        self.assertEqual("triple n+3 döndürüyor", case["answer_key"])
        self.assertEqual(2, case["defect_lines"])
        self.assertNotIn("mutate_error", case)
        diff = (self.out / "diffs" / "c1__defect.diff").read_text(encoding="utf-8")
        self.assertIn("+def triple(n):", diff)
        self.assertIn("+    return n + 3", diff)
        self.assertIn("n + 3", (self.out / "wt" / "c1__defect" / "src" / "calc.py").read_text(encoding="utf-8"))
        self.assertTrue((self.out / "cases" / "c1.mutate1.jsonl").exists())
        sent = calls(directory)[0]
        self.assertEqual(["run", "--standalone", "-m", "opencode-go/glm-5.3-flash#max", "--format", "json"],
                         sent[:6])
        self.assertIn(SPEC.strip(), sent[6])
        self.assertIn("src/calc.py", sent[6])
        self.assertIn("EDGE", sent[6])
        self.assertEqual(str(self.out / "wt" / "c1__defect"), pwds(directory)[0])

    def test_mutate_runs_the_model_under_sandbox_exec_with_a_case_profile(self):
        self.build()
        self.mutate_normally()
        if sys.platform != "darwin":
            self.skipTest("sandbox-exec is macOS only")
        shim_calls = (self.sandbox_bin / "calls.txt").read_text(encoding="utf-8")
        profile = self.out / "sandbox" / "c1.sb"
        self.assertTrue(profile.exists())
        self.assertIn(f"-f {profile}", shim_calls)
        text = profile.read_text(encoding="utf-8")
        self.assertIn("(deny file-write*", text)
        self.assertIn(os.path.realpath(str(self.out / "wt" / "c1__defect")), text)
        self.assertIn(os.path.realpath(tempfile.gettempdir()), text)
        self.assertIn("/private/var/folders", text)
        self.assertIn("/dev", text)

    def test_a_missing_sandbox_exec_fails_closed(self):
        if sys.platform != "darwin":
            self.skipTest("sandbox-exec is macOS only")
        self.build()
        empty = Path(self.tmp) / "empty-bin"
        empty.mkdir()
        saved = os.environ.get("PATH", "")
        os.environ["PATH"] = str(empty)
        try:
            with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
                corpus.cmd_mutate(str(self.out))
        finally:
            os.environ["PATH"] = saved
        self.assertEqual("built", self.load()["status"])

    def test_a_write_to_another_repo_is_a_stray_write_and_stops_mutate(self):
        other, _, other_commit = make_repo(self.tmp, {"src/other.py": "x\n"}, {"src/other.py": "y\n"},
                                           name="other-repo")
        self.build([self.entry("a"), case_entry(other, self.spec, self.hidden, other_commit, "b")])
        script, directory = fake(self.tmp, "mut", edits=[{"src/calc.py": DEFECT_CALC}],
                                 answers=['{"file": "src/calc.py", "answer_key": "x"}'],
                                 foreign={str(other / "src" / "other.py"): "hacked\n"})
        proc = cli("mutate", self.out, opencode=script, path_prefix=self.sandbox_bin, expect_ok=False)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("stray_write", proc.stderr)
        case = self.load("a")
        self.assertEqual("mutate_failed", case["status"])
        self.assertIn(f"stray_write: {other}", case["mutate_error"])
        self.assertEqual("built", self.load("b")["status"])
        self.assertEqual(1, len(calls(directory)))

    def test_a_file_outside_ref_files_is_rejected_and_the_worktree_is_reset(self):
        self.build()
        self.mutate_normally(edits=[{"src/other.py": "def one():\n    return 2\n"}])
        case = self.load()
        self.assertEqual("mutate_failed", case["status"])
        self.assertIn("out_of_scope", case["mutate_error"])
        self.assertEqual("", git(self.out / "wt" / "c1__defect", "status", "--porcelain").strip())

    def test_a_new_untracked_file_outside_ref_files_is_rejected_and_removed(self):
        self.build()
        self.mutate_normally(edits=[{"src/new_thing.py": "def x():\n    return 1\n"}])
        case = self.load()
        self.assertEqual("mutate_failed", case["status"])
        self.assertIn("out_of_scope", case["mutate_error"])
        self.assertIn("src/new_thing.py", case["mutate_error"])
        wt = self.out / "wt" / "c1__defect"
        self.assertEqual("", git(wt, "status", "--porcelain").strip())
        self.assertFalse((wt / "src" / "new_thing.py").exists())

    def test_a_test_file_is_rejected(self):
        repo, base, commit = make_repo(self.tmp, {
            "src/calc.py": BASE_CALC, "tests/test_calc.py": "def test_ok():\n    assert True\n"},
            {"src/calc.py": FEAT_CALC,
             "tests/test_calc.py": "def test_ok():\n    assert 1\n"}, name="repo2")
        entry = case_entry(repo, self.spec, self.hidden, commit)
        self.build([entry])
        self.assertEqual(["src/calc.py", "tests/test_calc.py"], self.load()["ref_files"])
        self.mutate_normally(edits=[{"tests/test_calc.py": "def test_ok():\n    assert False\n"}])
        case = self.load()
        self.assertEqual("mutate_failed", case["status"])
        self.assertIn("test_file", case["mutate_error"])

    def test_more_than_thirty_changed_lines_are_rejected(self):
        self.build()
        grown = FEAT_CALC + "".join(f"def extra_{i}():\n    return {i}\n\n" for i in range(16))
        self.mutate_normally(edits=[{"src/calc.py": grown}])
        case = self.load()
        self.assertEqual("mutate_failed", case["status"])
        self.assertIn("lines:", case["mutate_error"])

    def test_an_answer_without_the_json_object_fails_after_two_attempts(self):
        self.build()
        _, directory = self.mutate_normally(edits=[{}, {}], answers=["no json here", "still nothing"])
        case = self.load()
        self.assertEqual("mutate_failed", case["status"])
        self.assertEqual("no_json", case["mutate_error"])
        self.assertEqual(2, len(calls(directory)))
        self.assertTrue((self.out / "cases" / "c1.mutate1.jsonl").exists())
        self.assertTrue((self.out / "cases" / "c1.mutate2.jsonl").exists())

    def test_an_empty_answer_is_no_json_not_raw_stdout(self):
        self.build()
        self.mutate_normally(edits=[{}, {}], answers=["", ""])
        case = self.load()
        self.assertEqual("mutate_failed", case["status"])
        self.assertEqual("no_json", case["mutate_error"])

    def test_ids_limits_the_run_to_the_listed_cases(self):
        self.build([self.entry("a"), self.entry("b")])
        script, _ = fake(self.tmp, "mut", edits=[{"src/calc.py": DEFECT_CALC}],
                         answers=['{"file": "src/calc.py", "answer_key": "x"}'])
        self.mutate(script, "--ids", "a")
        self.assertEqual("mutated", self.load("a")["status"])
        self.assertEqual("built", self.load("b")["status"])

    def test_a_second_mutate_call_does_not_exceed_two_attempts_in_total(self):
        self.build()
        script, directory = fake(self.tmp, "mut", edits=[{}, {}], answers=["no json", "no json"])
        self.mutate(script)
        self.assertEqual("mutate_failed", self.load()["status"])
        self.mutate(script)
        self.assertEqual("mutate_failed", self.load()["status"])
        self.assertEqual(2, len(calls(directory)))
        self.assertEqual(2, self.load()["attempts"])
        self.assertFalse((self.out / "cases" / "c1.mutate3.jsonl").exists())

    def test_the_answer_file_must_be_one_of_the_changed_files(self):
        self.build()
        edits = [{"src/calc.py": DEFECT_CALC}] * 2
        answers = ['{"file": "src/other.py", "answer_key": "yanlis dosya"}'] * 2
        script, _ = fake(self.tmp, "mut", edits=edits, answers=answers)
        self.mutate(script)
        case = self.load()
        self.assertEqual("mutate_failed", case["status"])
        self.assertIn("file:", case["mutate_error"])
        self.assertEqual("", git(self.out / "wt" / "c1__defect", "status", "--porcelain").strip())

    def test_a_model_commit_is_rejected_and_the_worktree_returns_to_the_commit(self):
        self.build()
        script, _ = fake(self.tmp, "mut", edits=[{"src/calc.py": DEFECT_CALC}] * 2,
                         answers=['{"file": "src/calc.py", "answer_key": "x"}'] * 2, commit=True)
        self.mutate(script)
        case = self.load()
        self.assertEqual("mutate_failed", case["status"])
        self.assertIn("head_moved", case["mutate_error"])
        wt = self.out / "wt" / "c1__defect"
        self.assertEqual(self.commit, git(wt, "rev-parse", "HEAD").strip())
        self.assertEqual("", git(wt, "status", "--porcelain").strip())

    def test_reset_returns_the_commit_and_drops_gitignored_files(self):
        self.build()
        wt = self.out / "wt" / "c1__defect"
        (wt / ".gitignore").write_text("junk.txt\n", encoding="utf-8")
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "model commit")
        (wt / "junk.txt").write_text("junk\n", encoding="utf-8")
        corpus.reset_worktree(wt, self.commit)
        self.assertEqual(self.commit, git(wt, "rev-parse", "HEAD").strip())
        self.assertFalse((wt / "junk.txt").exists())
        self.assertFalse((wt / ".gitignore").exists())
        self.assertEqual("", git(wt, "status", "--porcelain").strip())


class CheckTest(CorpusTestCase):
    def test_passing_clean_case_becomes_valid(self):
        self.build()
        self.mutate_normally()
        proc = cli("check", self.out)
        case = self.load()
        self.assertEqual("valid", case["status"])
        self.assertEqual({"setup": "skipped", "tests": "pass", "hidden": "pass"}, case["clean"])
        self.assertEqual({"setup": "skipped", "tests": "pass", "hidden": "fail"}, case["defect"])
        for step in ("setup", "tests", "hidden"):
            for variant in ("clean", "defect"):
                log = self.out / "cases" / f"c1.{variant}.{step}.log"
                self.assertTrue(log.exists(), log)
                self.assertLessEqual(len(log.read_text(encoding="utf-8").splitlines()), 60)
        self.assertIn("check: 1 valid, 0 invalid", proc.stdout)

    def test_failing_clean_hidden_command_makes_the_case_invalid(self):
        self.build(hidden_cmd="python3 -c \"import sys; sys.exit(1)\"")
        self.mutate_normally()
        cli("check", self.out)
        case = self.load()
        self.assertEqual("invalid", case["status"])
        self.assertIn("clean.hidden", case["invalid_reason"])

    def test_a_failing_setup_skips_the_test_commands(self):
        self.build(setup="exit 3")
        self.mutate_normally()
        cli("check", self.out)
        case = self.load()
        self.assertEqual("invalid", case["status"])
        self.assertEqual("fail", case["clean"]["setup"])
        self.assertEqual("skipped", case["clean"]["tests"])
        self.assertEqual("skipped", case["clean"]["hidden"])
        self.assertIn("clean.setup", case["invalid_reason"])
        self.assertFalse((self.out / "cases" / "c1.clean.tests.log").exists())

    def test_invalid_reason_lists_every_step_that_did_not_pass_including_skipped(self):
        self.build(hidden_cmd="python3 -c \"import sys; sys.exit(1)\"")
        self.mutate_normally()
        cli("check", self.out)
        case = self.load()
        self.assertEqual("invalid", case["status"])
        # An empty setup ("skipped") is not a reason; skipped tests/hidden steps are.
        self.assertNotIn("clean.setup", case["invalid_reason"])
        self.assertIn("clean.hidden", case["invalid_reason"])
        self.assertNotIn("clean.tests", case["invalid_reason"])

    def test_a_setup_timeout_is_a_reason_and_skips_the_tests(self):
        self.build(setup="sleep 5")
        self.mutate_normally()
        saved = corpus.TIMEOUT
        corpus.TIMEOUT = 0.2
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                corpus.cmd_check(str(self.out))
        finally:
            corpus.TIMEOUT = saved
        case = self.load()
        self.assertEqual("timeout", case["clean"]["setup"])
        self.assertEqual("skipped", case["clean"]["tests"])
        self.assertIn("clean.setup", case["invalid_reason"])
        self.assertFalse((self.out / "cases" / "c1.clean.tests.log").exists())


class SplitTest(CorpusTestCase):
    def seed(self, count, status="valid"):
        directory = self.out / "cases"
        directory.mkdir(parents=True, exist_ok=True)
        for index in range(count):
            (directory / f"c{index}.json").write_text(
                json.dumps({"id": f"c{index}", "status": status}), encoding="utf-8")

    def test_ceil_half_goes_to_tuning_and_the_split_is_stable(self):
        self.seed(5)
        cli("split", self.out)
        split = json.loads((self.out / "split.json").read_text(encoding="utf-8"))
        self.assertEqual(46, split["seed"])
        self.assertEqual(3, len(split["tuning"]))
        self.assertEqual(2, len(split["holdout"]))
        self.assertEqual(sorted(split["tuning"] + split["holdout"]), sorted(split["tuning"] + split["holdout"]))
        self.assertEqual(sorted(split["tuning"] + split["holdout"]), ["c0", "c1", "c2", "c3", "c4"])
        self.assertEqual(sorted(split["tuning"]), split["tuning"])
        self.assertEqual(sorted(split["holdout"]), split["holdout"])
        again = cli("split", self.out)
        self.assertEqual(split, json.loads((self.out / "split.json").read_text(encoding="utf-8")))
        self.assertIn("split: 3 tuning, 2 holdout", again.stdout)

    def test_custom_seed_changes_the_membership(self):
        self.seed(8)
        cli("split", self.out, "--seed", "46")
        first = json.loads((self.out / "split.json").read_text(encoding="utf-8"))
        cli("split", self.out, "--seed", "7")
        second = json.loads((self.out / "split.json").read_text(encoding="utf-8"))
        self.assertEqual(7, second["seed"])
        self.assertNotEqual((first["tuning"], first["holdout"]), (second["tuning"], second["holdout"]))


class ReviewPackTest(CorpusTestCase):
    def seed_valid(self, case_id="c1", defect_hidden="fail"):
        (self.out / "cases").mkdir(parents=True, exist_ok=True)
        case = self.entry(case_id)
        case.update({"base": self.base, "ref_files": ["src/calc.py"], "class": "EDGE", "status": "valid",
                     "clean": {"setup": "skipped", "tests": "pass", "hidden": "pass"},
                     "defect": {"setup": "skipped", "tests": "pass", "hidden": defect_hidden}})
        (self.out / "cases" / f"{case_id}.json").write_text(json.dumps(case), encoding="utf-8")
        clean_diff = git(self.repo, "diff", self.base, self.commit)
        defect_diff = clean_diff.replace("+    return n * 3", "+    return n + 3")
        (self.out / "diffs").mkdir(exist_ok=True)
        (self.out / "diffs" / f"{case_id}__clean.diff").write_text(clean_diff, encoding="utf-8")
        (self.out / "diffs" / f"{case_id}__defect.diff").write_text(defect_diff, encoding="utf-8")
        return clean_diff, defect_diff

    def test_gates_and_blind_inputs_are_written(self):
        clean_diff, _ = self.seed_valid()
        cli("split", self.out)
        proc = cli("review-pack", self.out)
        gate = json.loads((self.out / "gates" / "c1__clean.txt").read_text(encoding="utf-8"))
        self.assertEqual({"changed": ["src/calc.py"], "tests": "pass", "hidden": "pass", "gate": "PASS"}, gate)
        bad = json.loads((self.out / "gates" / "c1__defect.txt").read_text(encoding="utf-8"))
        self.assertEqual("FAIL", bad["gate"])
        entries = json.loads((self.out / "review_inputs.json").read_text(encoding="utf-8"))
        self.assertEqual(2, len(entries))
        entry = entries[0]
        self.assertEqual({"item", "case", "variant", "split", "spec", "diff", "gate"}, set(entry))
        self.assertEqual("c1__clean", entry["item"])
        self.assertEqual("tuning", entry["split"])
        self.assertEqual(str(self.spec), entry["spec"])
        digest = hashlib.sha1(b"c1__clean").hexdigest()[:10]
        self.assertEqual(str(self.out / "blind" / f"{digest}.diff"), entry["diff"])
        self.assertEqual(str(self.out / "blind" / f"{digest}.txt"), entry["gate"])
        self.assertEqual(clean_diff, (self.out / "blind" / f"{digest}.diff").read_text(encoding="utf-8"))
        for value in (entry["diff"], entry["gate"]):
            self.assertNotIn("clean", value)
            self.assertNotIn("defect", value)
            self.assertNotIn("EDGE", value)
        self.assertIn("review-pack: 2 items", proc.stdout)

    def test_stale_blind_files_are_removed_before_writing(self):
        self.seed_valid()
        cli("split", self.out)
        blind = self.out / "blind"
        blind.mkdir()
        (blind / "stale.diff").write_text("old\n", encoding="utf-8")
        cli("review-pack", self.out)
        self.assertFalse((blind / "stale.diff").exists())
        self.assertEqual(4, len(list(blind.iterdir())))

    def test_a_valid_case_missing_from_the_split_is_an_error(self):
        self.seed_valid()
        cli("split", self.out)
        second = json.loads((self.out / "cases" / "c1.json").read_text(encoding="utf-8"))
        second["id"] = "c2"
        (self.out / "cases" / "c2.json").write_text(json.dumps(second), encoding="utf-8")
        proc = cli("review-pack", self.out, expect_ok=False)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("c2", proc.stderr)
        self.assertFalse((self.out / "review_inputs.json").exists())

    def test_review_pack_without_split_json_asks_for_split_first(self):
        self.seed_valid()
        proc = cli("review-pack", self.out, expect_ok=False)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("split", proc.stderr)
        self.assertFalse((self.out / "review_inputs.json").exists())


class ScoreTest(CorpusTestCase):
    def seed(self, case_id="c1", answer_key="triple n+3 döndürüyor", defect_hidden="fail", split=True):
        case = self.entry(case_id)
        case.update({"base": self.base, "ref_files": ["src/calc.py"], "class": "EDGE", "status": "valid",
                     "answer_key": answer_key,
                     "clean": {"setup": "skipped", "tests": "pass", "hidden": "pass"},
                     "defect": {"setup": "skipped", "tests": "pass", "hidden": defect_hidden}})
        (self.out / "cases").mkdir(parents=True, exist_ok=True)
        (self.out / "diffs").mkdir(exist_ok=True)
        (self.out / "cases" / f"{case_id}.json").write_text(json.dumps(case), encoding="utf-8")
        clean_diff = git(self.repo, "diff", self.base, self.commit)
        (self.out / "diffs" / f"{case_id}__clean.diff").write_text(clean_diff, encoding="utf-8")
        (self.out / "diffs" / f"{case_id}__defect.diff").write_text(clean_diff, encoding="utf-8")
        if split:
            cli("split", self.out)

    def review(self, label, item, text):
        directory = self.out / "reviews" / label
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{item}.md").write_text(text, encoding="utf-8")

    def test_a_review_that_flags_the_defect_counts_as_caught(self):
        self.seed()
        self.review("lab", "c1__clean", "ONAY\ntemiz görünüyor\n")
        self.review("lab", "c1__defect", "RED\ntriple yanlış topluyor\n")
        script, directory = fake(self.tmp, "grader", answers=["EVET\naynı hata", "EVET\naynı hata"])
        proc = cli("score", self.out, "lab", opencode=script)
        report = json.loads((self.out / "score_lab.json").read_text(encoding="utf-8"))
        self.assertEqual(1, report["total"]["n_defect"])
        self.assertEqual(1, report["total"]["caught"])
        self.assertEqual(1.0, report["total"]["catch_rate"])
        self.assertEqual(0, report["total"]["false_red"])
        self.assertEqual(0.0, report["total"]["false_red_rate"])
        self.assertEqual(0, report["total"]["unsure"])
        self.assertEqual(1.0, report["total"]["caught_hidden_rate"])
        self.assertEqual(0.0, report["total"]["caught_visible_rate"])
        defect = [item for item in report["items"] if item["variant"] == "defect"][0]
        self.assertEqual(["EVET", "EVET"], defect["grader"]["verdicts"])
        self.assertEqual(2, len(calls(directory)))
        prompt = calls(directory)[0][6]
        self.assertIn("triple n+3 döndürüyor", prompt)
        self.assertIn("triple yanlış topluyor", prompt)
        self.assertTrue(proc.stdout.strip().splitlines()[-1].startswith("score:"))

    def test_an_onay_on_the_defect_is_not_caught_and_needs_no_grader(self):
        self.seed()
        self.review("lab", "c1__defect", "  ONAY  \nher şey yolunda\n")
        self.review("lab", "c1__clean", "RED\nşüpheli\n")
        script, directory = fake(self.tmp, "grader", answers=["EVET\nx", "EVET\nx"])
        cli("score", self.out, "lab", opencode=script)
        report = json.loads((self.out / "score_lab.json").read_text(encoding="utf-8"))
        self.assertEqual(0, report["total"]["caught"])
        self.assertEqual(1, report["total"]["false_red"])
        self.assertEqual(1.0, report["total"]["false_red_rate"])
        self.assertEqual(0, len(calls(directory)))

    def test_disagreeing_graders_are_unsure_and_not_caught(self):
        self.seed()
        self.review("lab", "c1__defect", "RED\nbaşka bir sorun\n")
        script, _ = fake(self.tmp, "grader", answers=["EVET\nbelki", "HAYIR\ndeğil"])
        cli("score", self.out, "lab", opencode=script)
        report = json.loads((self.out / "score_lab.json").read_text(encoding="utf-8"))
        self.assertEqual(0, report["total"]["caught"])
        self.assertEqual(1, report["total"]["unsure"])

    def test_both_hayir_is_not_caught_and_not_unsure(self):
        self.seed()
        self.review("lab", "c1__defect", "RED\nbaşka bir sorun\n")
        script, _ = fake(self.tmp, "grader", answers=["HAYIR\nyok", "HAYIR\nyok"])
        cli("score", self.out, "lab", opencode=script)
        report = json.loads((self.out / "score_lab.json").read_text(encoding="utf-8"))
        self.assertEqual(0, report["total"]["caught"])
        self.assertEqual(0, report["total"]["unsure"])

    def test_grader_answers_are_cached(self):
        self.seed()
        self.review("lab", "c1__defect", "RED\nhata\n")
        script, directory = fake(self.tmp, "grader", answers=["EVET\na", "HAYIR\nb"])
        cli("score", self.out, "lab", opencode=script)
        self.assertTrue((self.out / "reviews" / "lab" / "c1__defect.grade.json").exists())
        cache = json.loads((self.out / "reviews" / "lab" / "c1__defect.grade.json").read_text(encoding="utf-8"))
        self.assertEqual(["EVET", "HAYIR"], cache["verdicts"])
        cli("score", self.out, "lab", opencode=script)
        self.assertEqual(2, len(calls(directory)))
        report = json.loads((self.out / "score_lab.json").read_text(encoding="utf-8"))
        self.assertEqual(1, report["total"]["unsure"])

    def test_an_empty_grader_answer_is_a_grader_error_and_not_cached(self):
        self.seed()
        self.review("lab", "c1__defect", "RED\nhata\n")
        script, _ = fake(self.tmp, "grader", answers=["", ""])
        cli("score", self.out, "lab", opencode=script)
        report = json.loads((self.out / "score_lab.json").read_text(encoding="utf-8"))
        self.assertEqual(1, report["total"]["grader_error"])
        self.assertEqual(0, report["total"]["caught"])
        self.assertIsNone(report["total"]["catch_rate"])
        self.assertFalse((self.out / "reviews" / "lab" / "c1__defect.grade.json").exists())

    def test_a_grader_that_cannot_run_is_a_grader_error_and_not_cached(self):
        self.seed()
        self.review("lab", "c1__defect", "RED\nhata\n")
        cli("score", self.out, "lab", opencode=Path(self.tmp) / "missing-opencode")
        report = json.loads((self.out / "score_lab.json").read_text(encoding="utf-8"))
        self.assertEqual(1, report["total"]["grader_error"])
        self.assertIsNone(report["total"]["catch_rate"])
        self.assertFalse((self.out / "reviews" / "lab" / "c1__defect.grade.json").exists())

    def test_a_valid_case_missing_from_the_split_is_an_error(self):
        self.seed()
        second = json.loads((self.out / "cases" / "c1.json").read_text(encoding="utf-8"))
        second["id"] = "c2"
        (self.out / "cases" / "c2.json").write_text(json.dumps(second), encoding="utf-8")
        proc = cli("score", self.out, "lab", opencode=Path(self.tmp) / "missing-opencode", expect_ok=False)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("c2", proc.stderr)

    def test_score_without_split_json_asks_for_split_first(self):
        self.seed(split=False)
        self.review("lab", "c1__defect", "RED\nhata\n")
        script, _ = fake(self.tmp, "grader", answers=["EVET\na", "EVET\nb"])
        proc = cli("score", self.out, "lab", opencode=script, expect_ok=False)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("split", proc.stderr)
        self.assertFalse((self.out / "score_lab.json").exists())

    def test_the_grader_runs_in_an_empty_scratch_directory(self):
        self.seed()
        self.review("lab", "c1__defect", "RED\nhata\n")
        script, directory = fake(self.tmp, "grader", answers=["EVET\na", "EVET\nb"])
        cli("score", self.out, "lab", opencode=script)
        seen = cwds(directory)
        self.assertEqual(2, len(seen))
        for cwd in seen:
            self.assertNotIn(str(self.out), cwd)
            self.assertFalse(Path(cwd).exists(), cwd)
        self.assertEqual([os.path.realpath(cwd) for cwd in seen],
                         [os.path.realpath(pwd) for pwd in pwds(directory)])
        sent = calls(directory)[0]
        self.assertEqual(["run", "--standalone", "-m", corpus.GRADER_MODEL, "--format", "json"], sent[:6])

    def test_the_grade_cache_belongs_to_the_grader_model(self):
        self.seed()
        self.review("lab", "c1__defect", "RED\nhata\n")
        script, directory = fake(self.tmp, "grader",
                                 answers=["EVET\na", "EVET\na", "HAYIR\nb", "HAYIR\nb"])
        cli("score", self.out, "lab", opencode=script)
        self.assertEqual(2, len(calls(directory)))
        cache = json.loads((self.out / "reviews" / "lab" / "c1__defect.grade.json").read_text(encoding="utf-8"))
        self.assertEqual(corpus.GRADER_MODEL, cache["model"])
        cli("score", self.out, "lab", "--grader", "other/model", opencode=script)
        self.assertEqual(4, len(calls(directory)))
        cache = json.loads((self.out / "reviews" / "lab" / "c1__defect.grade.json").read_text(encoding="utf-8"))
        self.assertEqual("other/model", cache["model"])

    def test_a_defect_with_a_broken_setup_is_not_a_tester_catch(self):
        items = [
            {"variant": "defect", "setup": "fail", "tests": "skipped", "hidden": "skipped"},
            {"variant": "defect", "setup": "timeout", "tests": "skipped", "hidden": "skipped"},
            {"variant": "defect", "setup": "skipped", "tests": "pass", "hidden": "skipped"},
            {"variant": "defect", "setup": "skipped", "tests": "pass", "hidden": "fail"},
        ]
        stats = corpus.case_stats(items, "tuning")
        self.assertEqual(2, stats["defect_setup_broken"])
        self.assertEqual(1, stats["caught_hidden"])
        self.assertEqual(0.5, stats["caught_hidden_rate"])
        self.assertEqual(0, stats["caught_visible"])
        self.assertEqual(0.0, stats["caught_visible_rate"])

    def test_zero_denominators_report_none(self):
        self.seed()
        self.review("lab", "c1__clean", "ONAY\ntemiz\n")
        script, _ = fake(self.tmp, "grader")
        cli("score", self.out, "lab", opencode=script)
        report = json.loads((self.out / "score_lab.json").read_text(encoding="utf-8"))
        self.assertIsNone(report["total"]["catch_rate"])
        self.assertIsNone(report["total"]["caught_hidden_rate"])
        self.assertIsNone(report["total"]["caught_visible_rate"])
        (self.out / "reviews" / "lab" / "c1__clean.md").unlink()
        self.review("lab", "c1__defect", "ONAY\ntemiz\n")
        cli("score", self.out, "lab", opencode=script)
        report = json.loads((self.out / "score_lab.json").read_text(encoding="utf-8"))
        self.assertIsNone(report["total"]["false_red_rate"])


class PipelineTest(CorpusTestCase):
    def test_the_full_pipeline_packages_blind_inputs_and_scores_reviews(self):
        self.build()
        self.mutate_normally()
        cli("check", self.out)
        cli("split", self.out)
        cli("review-pack", self.out)
        entries = json.loads((self.out / "review_inputs.json").read_text(encoding="utf-8"))
        self.assertEqual(["c1__clean", "c1__defect"], [entry["item"] for entry in entries])
        self.assertTrue(all(entry["split"] in ("tuning", "holdout") for entry in entries))
        digest = hashlib.sha1(b"c1__clean").hexdigest()[:10]
        self.assertEqual(str(self.out / "blind" / f"{digest}.diff"), entries[0]["diff"])
        reviews = self.out / "reviews" / "lab"
        reviews.mkdir(parents=True)
        (reviews / "c1__clean.md").write_text("ONAY\ntemiz\n", encoding="utf-8")
        (reviews / "c1__defect.md").write_text("RED\ntriple bozuk\n", encoding="utf-8")
        script, _ = fake(self.tmp, "grader", answers=["EVET\nevet", "EVET\nevet"])
        proc = cli("score", self.out, "lab", opencode=script)
        report = json.loads((self.out / "score_lab.json").read_text(encoding="utf-8"))
        self.assertEqual(1, report["total"]["n_defect"])
        self.assertEqual(1, report["total"]["caught"])
        self.assertEqual(0, report["total"]["false_red"])
        self.assertEqual(1.0, report["total"]["catch_rate"])
        by_item = {item["item"]: item for item in report["items"]}
        self.assertEqual(entries[0]["split"], by_item["c1__clean"]["split"])
        self.assertEqual(["EVET", "EVET"], by_item["c1__defect"]["grader"]["verdicts"])
        self.assertIn("c1__defect.grade.json", os.listdir(reviews))
        self.assertTrue(proc.stdout.strip().splitlines()[-1].startswith("score:"))


class CleanTest(CorpusTestCase):
    def test_only_the_corpus_worktrees_are_removed(self):
        self.build()
        other = Path(self.tmp) / "other-wt"
        git(self.repo, "worktree", "add", "--detach", str(other), self.commit)
        proc = cli("clean", self.out)
        self.assertFalse((self.out / "wt" / "c1__clean").exists())
        self.assertFalse((self.out / "wt" / "c1__defect").exists())
        self.assertTrue((other / "src" / "calc.py").exists())
        listing = git(self.repo, "worktree", "list")
        self.assertIn(str(other), listing)
        self.assertNotIn("c1__clean", listing)
        self.assertIn("clean: 2 worktrees removed", proc.stdout)


    def test_worktrees_are_removed_even_without_case_records(self):
        self.build()
        (self.out / "cases" / "c1.json").unlink()
        proc = cli("clean", self.out)
        self.assertFalse((self.out / "wt" / "c1__clean").exists())
        self.assertFalse((self.out / "wt" / "c1__defect").exists())
        self.assertIn("clean: 2 worktrees removed", proc.stdout)

    def test_directories_that_are_not_worktrees_are_left_alone(self):
        self.build()
        stray = self.out / "wt" / "stray"
        stray.mkdir()
        (stray / "keep.txt").write_text("keep\n", encoding="utf-8")
        proc = cli("clean", self.out)
        self.assertTrue((stray / "keep.txt").exists())
        self.assertIn("clean: 2 worktrees removed", proc.stdout)


class CliTest(unittest.TestCase):
    def test_an_unknown_subcommand_exits_non_zero(self):
        proc = cli("bogus", expect_ok=False)
        self.assertNotEqual(0, proc.returncode)

    def test_no_subcommand_exits_non_zero(self):
        proc = cli(expect_ok=False)
        self.assertNotEqual(0, proc.returncode)


class HelperTest(unittest.TestCase):
    def test_class_cycle(self):
        self.assertEqual(["EDGE", "SWALLOW", "REGRESS", "SCOPE", "SECURITY", "BOUNDARY", "ORDER", "EDGE"],
                         [corpus.class_for(index) for index in range(8)])

    def test_is_test_path(self):
        for path in ("tests/test_a.py", "src/test_app.py", "src/app_test.py", "src/app.test.js",
                     "src/__tests__/app.js", "pkg/tests/helper.py", "src/tests/x.py",
                     "src/test_helpers/x.py", "pkg/test_mod/app.py"):
            self.assertTrue(corpus.is_test_path(path), path)
        for path in ("src/app.py", "src/contest.py", "src/testing.py", "README.md",
                     "src/latest_x.py", "src/mytests/x.py"):
            self.assertFalse(corpus.is_test_path(path), path)

    def test_last_json_object(self):
        answer = 'reasoning\n```json\n{"file": "a.py", "answer_key": "bir"}\n```\ntrailing prose'
        self.assertEqual({"file": "a.py", "answer_key": "bir"}, corpus.last_json_object(answer))
        self.assertEqual({"b": {"c": 1}}, corpus.last_json_object('x {"a": } {"b": {"c": 1}} y'))
        self.assertIsNone(corpus.last_json_object("no object"))
        self.assertIsNone(corpus.last_json_object("{broken"))

    def test_verdicts(self):
        self.assertEqual("ONAY", corpus.read_verdict("\n  ONAY  \nreason"))
        self.assertEqual("RED", corpus.read_verdict("ONAY dedim\n"))
        self.assertEqual("RED", corpus.read_verdict(""))
        self.assertEqual("EVET", corpus.grader_verdict("\nEVET\nreason"))
        self.assertEqual("HAYIR", corpus.grader_verdict("evet\n"))
        self.assertEqual("HAYIR", corpus.grader_verdict(""))

    def test_fill_does_not_expand_inserted_text(self):
        out = corpus.fill("{A} {B} {MISSING}", {"{A}": "{B}", "{B}": "x"})
        self.assertEqual("{B} x {MISSING}", out)

    def test_fill_keeps_unmatched_braces_and_fills_later_placeholders(self):
        # The template's JSON example stays as-is even though it contains "{" and "}",
        # and a real placeholder after it is still filled.
        template = 'JSON ornegi: {"file": "a.py"}\n\nDIFF:\n{DIFF}\n'
        self.assertEqual('JSON ornegi: {"file": "a.py"}\n\nDIFF:\nthe diff\n',
                         corpus.fill(template, {"{DIFF}": "the diff"}))
        # An unknown "{"-run must not swallow a placeholder inside it.
        self.assertEqual("{no {PLACEHOLDER} match d", corpus.fill("{no {PLACEHOLDER} match {D}", {"{D}": "d"}))
        # An unknown placeholder itself is left untouched.
        self.assertEqual("{MISSING} x", corpus.fill("{MISSING} {A}", {"{A}": "x"}))

    def test_diff_files(self):
        diff = ("diff --git a/src/calc.py b/src/calc.py\n--- a/src/calc.py\n+++ b/src/calc.py\n"
                "diff --git a/b.txt b/b.txt\n")
        self.assertEqual(["src/calc.py", "b.txt"], corpus.diff_files(diff))

    def test_diff_files_keeps_paths_with_spaces_and_c_quoted_bytes(self):
        diff = ('diff --git a/my file.txt b/my file.txt\n'
                'diff --git "a/t\\303\\274rk.txt" "b/t\\303\\274rk.txt"\n'
                'diff --git a/old.txt b/new.txt\n')
        self.assertEqual(["my file.txt", "türk.txt", "new.txt"], corpus.diff_files(diff))

    def test_parse_answer_reports_the_reason(self):
        text, error = corpus.parse_answer('{"type": "text", "part": {"messageID": "m", "text": "merhaba"}}')
        self.assertEqual("merhaba", text)
        self.assertIsNone(error)
        text, error = corpus.parse_answer('{"type": "text", "part": "bozuk"}')
        self.assertEqual("", text)
        self.assertTrue(error.startswith("no_json: "), error)


if __name__ == "__main__":
    unittest.main()
